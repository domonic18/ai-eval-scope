"""PackageToolServer — 场景包工程沙盒工具面。

核心不变量：**磁盘上的包任何时刻只见过「用户确认且校验通过」的内容**——
写操作一律进暂存区（内存 dict），宿主在 diff 确认 + 校验门禁通过后经
:meth:`commit` 原子提交（staging → disk）。

读写分级（Claude Code 式文件工具机制）：
- **写**（write_file / delete_file）：硬沙盒——路径 ``resolve()`` 后必须位于包根内
  （防 ``..`` 与 symlink 逃逸），扩展名白名单 ``.yaml/.yml/.json/.md``，
  ``sut_configs/`` 凭证明文拒绝；无 shell、无网络、无包外写；
- **读**（read_file / list_files）分级授权：会话根内（暂存视图优先）→ 随包资源
  ``assets/``（自动授权只读）→ 外部路径经 ``ask_fn`` 向用户申请授权（拒绝即拉黑）；
  凭证类路径（密钥区 / sut_sessions / .env）一律硬拒，先于授权——凭证不回流 LLM 上下文。

工具实现为普通异步方法（可直接调用与测试，零框架依赖），经
``ToolExporterMixin`` 惰性导出为 LangChain Tool 绑定给 DeepAgents
（对齐 sut_tools.py 范式）。错误以 ``{"error": ...}`` 返回值交 Agent
自修复（tool_guard 精神：不中断图）。
"""

from __future__ import annotations

import difflib
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any, cast

from agent_eval.agent.core.tools import ToolExporterMixin, ToolSpec, truncate
from agent_eval.config.paths import PACKAGE_ROOT
from agent_eval.packages import MANIFEST_FILENAME

_WRITE_EXTS = {".yaml", ".yml", ".json", ".md"}
# sut_configs 凭证明文启发式：<field>: <非空且非 ${VAR} 引用的值>
_CRED_FIELD_RE = re.compile(
    r"^\s*(password|token|api_key|secret)\s*:\s*([^#\n]+?)\s*$", re.MULTILINE
)

# 创建骨架（Plan-as-Artifact，arch/15 五阶段创建流程）：探测期只写骨架不写配置，
# 槽位机器可检——开槽 = ``- [ ]``（未验证），闭槽 = ``- [x]`` 且行内含「证据：」。
# 骨架是过程产物：validate 拦开槽，commit 排除出包并归档为审计产物
SKELETON_FILENAME = "SKELETON.md"
_MECHANICAL_SECTION = "## 机械实测事实（服务端追加，勿手改）"
_OPEN_SLOT_RE = re.compile(r"^\s*-\s\[\s\]")
_CLOSED_SLOT_RE = re.compile(r"^\s*-\s\[[xX]\]\s*(.*)$")


def skeleton_gate_errors(skeleton: str) -> list[str]:
    """骨架开槽门禁：开槽未闭合 / 闭槽缺证据标注的错误清单（空 = 放行）。"""
    errors: list[str] = []
    open_slots = [line.strip() for line in skeleton.splitlines() if _OPEN_SLOT_RE.match(line)]
    if open_slots:
        shown = "\n".join(f"  {s}" for s in open_slots[:10])
        suffix = f"\n  …（共 {len(open_slots)} 条）" if len(open_slots) > 10 else ""
        errors.append(
            f"{SKELETON_FILENAME} 仍有 {len(open_slots)} 个未闭合槽位（- [ ]）——"
            "配置只在事实齐备后生成：事实槽按「机械实测事实」节的探测证据改写闭合"
            f"（- [x] + 证据：），决策槽经用户确认后闭合：\n{shown}{suffix}"
        )
    missing_evidence = [
        match.group(1).strip()
        for line in skeleton.splitlines()
        if (match := _CLOSED_SLOT_RE.match(line)) and "证据：" not in line
    ]
    if missing_evidence:
        errors.append(
            f"{SKELETON_FILENAME} 闭槽缺「证据：」标注（- [x] 行必含——闭槽 = 有证据的"
            f"结论）：{'；'.join(s[:60] for s in missing_evidence[:5])}"
        )
    return errors


# 随包发布资源根（自动授权只读域）：结构规范 / JSON Schema / 示例配置。
# 运行时资料禁止引用仓库文档路径（pip 安装用户没有仓库文档）
_ASSETS_ROOT = PACKAGE_ROOT / "assets"
_LIST_MAX_FILES = 200
# 工具签名缺省截断（LLM 可传参覆盖）：读长文件防上下文爆炸
_DEFAULT_READ_CHARS = 8_000  # read_file 单次正文
_DEFAULT_REFERENCE_CHARS = 6_000  # read_reference 内置包样例摘录

# 读取硬禁区（安全红线：凭证/token 不回流 LLM 上下文）——先于授权逻辑，用户同意也不可读：
# 密钥区 ~/.agent_eval/（platform/llm/sut_credentials 三文件）、SUT 会话 token、.env 键值
_CREDENTIAL_HINT_DIRS = {".agent_eval", "sut_sessions"}


def _is_credential_path(target: Path) -> bool:
    """凭证类路径判定：密钥区目录 / SUT 会话 token / .env（按约定名）。"""
    if target.name in (".env", "sut_credentials.json"):
        return True
    return any(part in _CREDENTIAL_HINT_DIRS for part in target.parts)


def _reference_notes() -> str:
    """内置包参照说明 + **真实文件树**（动态扫描）。

    给出实际清单而非示例名：Agent 按猜测路径 read_reference 失败时可直接
    从这里拿到正确的相对路径重试，避免放弃参照、凭记忆自创结构。
    """
    from agent_eval.packages import PackageManager

    lines = ["内置包参照（read_reference 的 ref 与 path 以此为准）："]
    for pkg in PackageManager().list(source="builtin"):
        files = sorted(p.relative_to(pkg.root).as_posix() for p in pkg.root.rglob("*.yaml"))
        lines.append(f"- {pkg.manifest.ref}（{len(files)} 个 yaml）: " + ", ".join(files))
    lines.append("read_reference 的 path 直接复制上面清单中的文件名（相对包根）")
    lines.append("内置包只是三源之一——全部包（含项目目录 *-package/）用 list_packages 查询")
    return "\n".join(lines)


def _is_credential_violation(content: str) -> str | None:
    """返回首个命中的凭证明文片段（None 表示干净）。``${VAR}`` 引用与空值放行。"""
    for match in _CRED_FIELD_RE.finditer(content):
        value = match.group(2).strip().strip("'\"")
        if not value or value.startswith("${"):
            continue
        if value.startswith("credential_ref"):
            continue
        return f"{match.group(1)}: {value[:12]}…"
    return None


class PackageToolServer(ToolExporterMixin):
    """场景包沙盒工具面（读写均过暂存区，宿主确认后才落盘）。"""

    # 与基类同形态（非 ClassVar）：ClassVar 遮蔽实例变量声明会被 mypy 拒绝
    TOOL_SPECS: list[ToolSpec] = [
        ToolSpec(
            "list_files",
            "列出目录文件：会话根内（含暂存态标记 added/staged/deleted/unchanged）或"
            "随包资源 assets/；外部目录向用户申请授权后为普通清单",
            "list_files",
        ),
        ToolSpec(
            "read_file",
            "读取文件：会话根内（暂存版本优先）/ 随包资源 assets/（自动授权只读，"
            "如 guides/scenario-package-format.md 包结构规范）/ 外部路径（向用户申请授权）",
            "read_file",
        ),
        ToolSpec(
            "write_file",
            "写入/新建包内文件（进暂存区，落盘需宿主确认+校验通过）",
            "write_file",
        ),
        ToolSpec("delete_file", "删除包内文件（进暂存区）", "delete_file"),
        ToolSpec("read_manifest", "读取 agent_eval.yaml 包清单（暂存版本优先）", "read_manifest"),
        ToolSpec(
            "update_manifest",
            "浅合并更新包清单字段（如 version/labels/default_rule_set）",
            "update_manifest",
        ),
        ToolSpec(
            "write_sut_config",
            "机械物化 sut_configs/ 配置（在线被测系统落盘的唯一正道）：filename 传"
            " sut_configs/<名字>.yaml 或裸名 <名字>.yaml（自动归位 sut_configs/）；"
            "只给决策字段（name/channel/base_url/timeout/request_template/"
            "response_mapping 等），auth: 段由服务端从本会话登录实测账本**原样注入**"
            "（不接受手写 auth）；装配后内联 schema 校验，幻觉字段当场打回",
            "write_sut_config",
        ),
        ToolSpec(
            "validate_package",
            "校验暂存视图（清单合法 + 资源目录 + 规则 YAML 可解析 + 骨架开槽检查），返回错误列表",
            "validate_package",
        ),
        ToolSpec(
            "list_packages",
            "列出全部已发现的场景包（builtin 内置 / local 本地缓存 / project 项目目录"
            "三源，与 scenario list 同源）——回答「有哪些包 / 有没有现成包」先调此工具，"
            "不要凭记忆或目录列举判断；读包内文件走 read_reference（按 ref）",
            "list_packages",
        ),
        ToolSpec(
            "search_reference",
            "检索内置包（chat/code/courseware）按文件名匹配，返回命中文件与各包真实"
            "文件清单（read_reference 的 path 以此为准）",
            "search_reference",
        ),
        ToolSpec(
            "read_reference",
            "只读已发现包（三源）的文件内容（ref 如 chat 或项目包 scenario/id，见 "
            "list_packages；path 为包内相对路径）——参照真实格式，read_file 仅限本包",
            "read_reference",
        ),
        ToolSpec(
            "list_evaluators",
            "列出当前可用的评估器注册 ID（注册表实时快照，含本包 entry_points 声明的）——"
            "rules 的 evaluator 字段从此清单原样复制，勿凭记忆臆造",
            "list_evaluators",
        ),
        ToolSpec(
            "preview_diff",
            "预览暂存区 vs 磁盘原文的统一 diff（宿主确认界面同源）",
            "preview_diff",
        ),
    ]

    def __init__(
        self,
        pkg_root: Path,
        *,
        assets_root: Path | None = None,
        ask_fn: Any = None,  # async (question, *, options, secret) -> str（外部读取授权）
    ) -> None:
        self.root = Path(pkg_root).resolve()
        self.assets_root = (assets_root or _ASSETS_ROOT).resolve()
        self.ask_fn = ask_fn
        # 外部路径授权账本（host 边界同款：允许记账放行 / 拒绝拉黑防反复试探）
        self._granted: set[Path] = set()
        self._denied: set[Path] = set()
        # 暂存区：rel_path(POSIX) -> 新内容；None 表示删除
        self.staging: dict[str, str | None] = {}
        # 创建骨架（过程产物，commit 排除出包）的最新完整文本——宿主归档为审计
        # 产物用；同时是跨轮暂存清除后 fact_sink 续写的种子（见 _skeleton_text）
        self.skeleton_archive: str | None = None
        # 探测证据账本（SUTProbeToolServer，agent.py 装配后绑定——两 server 构造
        # 互需对方能力，靠后绑定解环）：write_sut_config 机械注入 auth 的事实源
        self.ledger: Any = None

    # ─── 沙盒与视图 ───────────────────────────────────────────────

    def _resolve_in(self, rel_path: str) -> Path:
        """把相对路径解析到包根内；越界（../、绝对、symlink 逃逸）抛 ValueError。"""
        target = (self.root / rel_path).resolve()
        if not target.is_relative_to(self.root):
            raise ValueError(f"路径越出包根（沙盒拒绝）: {rel_path}")
        return target

    def _disk_text(self, abs_path: Path) -> str | None:
        try:
            return abs_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return None

    def _view(self) -> dict[str, str]:
        """磁盘视图 + 暂存覆盖的合并结果（None = 已删除的文件被过滤）。"""
        view: dict[str, str | None] = {}
        if self.root.is_dir():
            for p in sorted(self.root.rglob("*")):
                if p.is_file() and ".git" not in p.parts:
                    view[p.relative_to(self.root).as_posix()] = self._disk_text(p)
        view.update(self.staging)
        return cast(dict[str, str], {k: v for k, v in view.items() if v is not None})

    def view(self) -> dict[str, str]:
        """暂存视图（宿主门禁读取：如 agent_protocol 通道必须经 probe_protocol 实测）。"""
        return self._view()

    def rebind_root(self, new_root: Path) -> None:
        """重绑包根（包归位后调用）：后续读写/diff/门禁以新位置为准。

        会话中重定向沙盒零状态残留——staging 是内存 dict、root 无其它持久句柄，
        _resolve_in/_view/commit 均按 self.root 现取；调用时机（commit 之后，staging
        已清）保证无跨根脏暂存。
        """
        self.root = Path(new_root).resolve()

    # ─── 创建骨架（Plan-as-Artifact：服务端事实回填 + 开槽门禁） ───

    def _skeleton_text(self) -> str | None:
        """骨架当前文本：暂存优先，磁盘兜底，再兜底跨轮归档文本；无则 None。"""
        if (staged := self.staging.get(SKELETON_FILENAME)) is not None:
            return staged
        if SKELETON_FILENAME in self.staging:
            return None  # 暂存标记删除：以删除为准
        return self._disk_text(self.root / SKELETON_FILENAME) or self.skeleton_archive

    def append_skeleton_fact(self, fact_line: str) -> None:
        """探测验证成功的事实机械回填骨架（fact_sink 回调目标，非 Agent 工具）。

        事实行由探测工具服务端写就（不经 LLM 转述——验证结论到骨架的传递零变形），
        追加进「机械实测事实」节（无则在文末创建）；Agent 据此把对应开槽改写闭合。
        无骨架时静默忽略（骨架 opt-in：克隆/fork 既有包的会话不受影响）；
        回填失败不抛（事实sink 故障不阻断探测结论本身）。
        """
        text = self._skeleton_text()
        if text is None:
            return
        entry = f"- [x] {fact_line.strip()}"
        header = _MECHANICAL_SECTION + "\n"
        if header in text:
            head, _, tail = text.partition(header)
            new_text = head + header + entry + "\n" + tail
        else:
            new_text = text.rstrip("\n") + f"\n\n{_MECHANICAL_SECTION}\n{entry}\n"
        self.staging[SKELETON_FILENAME] = new_text

    # ─── 工具（Agent 可调用；错误以 {"error": ...} 返回） ─────────

    async def list_files(self, path: str = "") -> dict[str, Any]:
        """列目录文件（分级授权）。

        会话根内（空/相对路径，含暂存态标记）与随包资源 assets/ 直接列出；
        其余外部目录复用 read_file 的授权账本（拒绝即拉黑）。
        """
        candidate = Path(path) if path else self.root
        target = (candidate if candidate.is_absolute() else self.root / candidate).resolve()
        if _is_credential_path(target):
            return {"error": f"安全红线：凭证类位置不可列（不回流 LLM 上下文）: {target}"}
        in_session = target == self.root or target.is_relative_to(self.root)
        in_assets = target == self.assets_root or target.is_relative_to(self.assets_root)
        if not (in_session or in_assets):
            err = await self._ensure_grant(target, listing=True)
            if err:
                return {"error": err}
        if in_session and target == self.root:
            return self._list_session()
        if not target.is_dir():
            return {"error": f"不是目录或不存在: {target}"}
        files = sorted(
            p.relative_to(target).as_posix()
            for p in target.rglob("*")
            if p.is_file() and ".git" not in p.parts and not _is_credential_path(p)
        )
        listed = files[:_LIST_MAX_FILES]
        result: dict[str, Any] = {"root": str(target), "files": listed, "total": len(files)}
        if len(files) > len(listed):
            result["truncated"] = True
        return result

    def _list_session(self) -> dict[str, Any]:
        """会话根清单（含暂存状态标记）。"""
        staged = set(self.staging)
        on_disk = (
            {
                p.relative_to(self.root).as_posix()
                for p in self.root.rglob("*")
                if p.is_file() and ".git" not in p.parts
            }
            if self.root.is_dir()
            else set()
        )
        files = []
        for rel in sorted(on_disk | staged):
            if rel in self.staging:
                if self.staging[rel] is None:
                    files.append({"path": rel, "status": "deleted"})
                elif rel in on_disk:
                    files.append({"path": rel, "status": "staged"})
                else:
                    files.append({"path": rel, "status": "added"})
            else:
                files.append({"path": rel, "status": "unchanged"})
        return {"files": files, "root": str(self.root)}

    async def read_file(self, path: str, max_chars: int = _DEFAULT_READ_CHARS) -> dict[str, Any]:
        """读文件（分级授权）。

        会话根内（相对或根内绝对路径）→ 暂存视图优先；随包资源 assets/ → 自动授权
        只读；其余外部路径 → 经 ask_fn 向用户申请授权（拒绝即拉黑）。凭证路径一律
        硬拒（先于授权——红线：凭证/token 不回流 LLM 上下文）。
        """
        candidate = Path(path)
        target = (candidate if candidate.is_absolute() else self.root / candidate).resolve()
        if _is_credential_path(target):
            return {"error": f"安全红线：凭证类文件不可读（不回流 LLM 上下文）: {target}"}
        if target.is_relative_to(self.root):
            rel = target.relative_to(self.root).as_posix()
            if rel in self.staging:
                content = self.staging[rel]
                if content is None:
                    return {"error": f"文件已在暂存区标记删除: {rel}"}
            else:
                content = self._disk_text(target)
                if content is None:
                    return {"error": f"文件不存在或不可读: {rel}"}
            return {"path": rel, "content": truncate(content, max_chars)}
        if target.is_relative_to(self.assets_root):
            return self._read_raw(target, max_chars)
        err = await self._ensure_grant(target)
        if err:
            return {"error": err}
        return self._read_raw(target, max_chars)

    def _read_raw(self, abs_path: Path, max_chars: int) -> dict[str, Any]:
        try:
            content = abs_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            return {"error": f"文件不存在或不可读: {abs_path}（{e}）"}
        return {"path": str(abs_path), "content": truncate(content, max_chars)}

    async def _ensure_grant(self, target: Path, *, listing: bool = False) -> str | None:
        """外部路径授权门（host 边界同款：允许记账放行 / 拒绝拉黑）。None = 放行。"""
        for denied in (*self._denied,):
            if target == denied or target.is_relative_to(denied):
                return f"该路径此前已被用户拒绝，勿再试探: {target}"
        for granted in (*self._granted,):
            if target == granted or target.is_relative_to(granted):
                return None
        if self.ask_fn is None:
            return (
                f"会话根外的路径需用户授权{'列出' if listing else '读取'}: {target}"
                "（当前无交互通道——请把文件放入会话根目录后重试）"
            )
        verb = "列出目录" if listing else "读取文件"
        choice = await self.ask_fn(
            f"允许 Agent {verb}吗？（会话工作区之外）\n{target}",
            options=["允许", "拒绝"],
            secret=False,
        )
        if choice != "允许":
            self._denied.add(target)
            return f"用户拒绝{verb}: {target}"
        self._granted.add(target)
        return None

    async def write_file(self, path: str, content: str) -> dict[str, Any]:
        if Path(path).suffix not in _WRITE_EXTS:
            return {"error": f"扩展名不在白名单 {_WRITE_EXTS}: {path}"}
        try:
            abs_path = self._resolve_in(path)
        except ValueError as e:
            return {"error": str(e)}
        rel = abs_path.relative_to(self.root).as_posix()
        if rel.startswith("sut_configs/"):
            hit = _is_credential_violation(content)
            if hit:
                return {
                    "error": (
                        f"安全红线：sut_configs 禁止凭证明文（命中 {hit}）。"
                        "凭证经 credential_ref 引用，明文请录 agent-eval secrets set <ref>.<field>"
                    )
                }
        # YAML fail-fast 预检：截断/损坏内容当场打回（垃圾进不了暂存，省掉
        # 「靠 Agent read_file 自检才发现截断」的一整轮——实测事故）。update_manifest
        # 经此天然受益；sut_configs 的 schema 校验由 write_sut_config 另行负责
        if Path(path).suffix in (".yaml", ".yml"):
            import yaml

            try:
                yaml.safe_load(content)
            except yaml.YAMLError as e:
                return {
                    "error": (
                        f"YAML 解析失败（未入暂存区）{rel}: {e}——内容疑似被截断"
                        "或损坏，请整体重写完整文件"
                    )
                }
        self.staging[rel] = content
        return {"ok": True, "staged": rel, "note": "已入暂存区，落盘需宿主确认+校验通过"}

    async def delete_file(self, path: str) -> dict[str, Any]:
        try:
            abs_path = self._resolve_in(path)
        except ValueError as e:
            return {"error": str(e)}
        rel = abs_path.relative_to(self.root).as_posix()
        if rel not in self.staging and not abs_path.is_file():
            return {"error": f"文件不存在: {rel}"}
        self.staging[rel] = None
        return {"ok": True, "staged_delete": rel}

    async def read_manifest(self) -> dict[str, Any]:
        import yaml

        result = await self.read_file(MANIFEST_FILENAME)
        if "error" in result:
            return result
        try:
            data = yaml.safe_load(result["content"]) or {}
        except yaml.YAMLError as e:
            return {"error": f"清单 YAML 解析失败: {e}"}
        return {"manifest": data.get("package", data)}

    async def update_manifest(self, fields: dict[str, Any]) -> dict[str, Any]:
        import yaml

        current = await self.read_manifest()
        if "error" in current:
            return current
        merged = {**current["manifest"], **fields}
        # 包一层再 dump——曾手拼 "package:\n" + dump(扁平dict)，子键零缩进、
        # package: 为 null，落盘清单结构性损坏（read_manifest 的 get 回退又把
        # 坏结构读回「自洽」，diff 才暴露）；safe_dump 嵌套结构自带正确缩进
        content = "# 场景包清单（WorkbenchAgent 更新）\n" + yaml.safe_dump(
            {"package": merged}, allow_unicode=True, sort_keys=False
        )
        return await self.write_file(MANIFEST_FILENAME, content)

    async def write_sut_config(
        self, filename: str, sut: dict[str, Any], credential_ref: str = ""
    ) -> dict[str, Any]:
        """机械物化 sut_configs（五阶段创建流程阶段3）：auth 段从探测账本注入。

        filename 传 ``sut_configs/<名字>.yaml``（或裸名 ``<名字>.yaml``，自动归位
        sut_configs/）。Agent 只提供决策字段（name/channel/base_url/timeout/
        request_template/response_mapping…）；``auth:`` 段由服务端从本会话登录实测
        账本（declare_token 机械登记的 auth_snippet）**原样装配**——验证结论到落盘
        配置的传递不经 LLM 转述，「验证过了又来一遍」的重复实测从源头消失。
        装配后内联执行器同款 schema 校验（未知键当场打回——幻觉字段进不了暂存）。
        """
        import yaml

        from agent_eval.execution.registry import validate_sut_config_document

        if Path(filename).suffix not in (".yaml", ".yml"):
            return {"error": f"sut_config 须为 .yaml/.yml: {filename}"}
        # 裸名与带前缀两种写法都接受，机械归一为包内相对路径（凡可机械归一的变形
        # 不经 LLM 转述）——实测事故：守卫曾只认带前缀形态却自称「只写平铺文件」，
        # 裸名 <名字>.yaml 被拒（parent 是 "."）且错误不指路，Agent 误读为「勿带
        # 前缀」后在 payload 结构上找原因空转多轮
        name = Path(filename).name
        if Path(filename).parent.as_posix() not in (".", "sut_configs"):
            return {
                "error": (
                    f"write_sut_config 只写 sut_configs/ 下的平铺文件（不接受子目录）:"
                    f" {filename}——传 sut_configs/<名字>.yaml 或 <名字>.yaml"
                )
            }
        if "auth" in sut:
            return {
                "error": (
                    "auth 段由服务端从实测账本机械注入，不接受手写（防转述变形）——"
                    "去掉 auth 键，用 credential_ref 参数指定采用哪条实测记录"
                )
            }
        ref = (credential_ref or str(sut.get("name") or "")).strip()
        fact = self.ledger.verified_login(ref) if self.ledger is not None else None
        if fact is None:
            return {
                "error": (
                    f"credential_ref={ref!r} 在本会话没有已验证的登录实测——auth 段只能"
                    "出自实测账本。先用 request 实测登录（body 带凭证模板 + ref），2xx 后"
                    " declare_token 声明提取，再用本工具落盘；禁止凭记忆或参照示例手写 auth"
                )
            }
        auth = (yaml.safe_load(fact["auth_snippet"]) or {}).get("auth")
        doc: dict[str, Any] = {"sut": {**sut, "auth": auth}}
        if schema_errors := validate_sut_config_document(doc):
            return {
                "error": "sut_config schema 校验未通过（未入暂存）：\n- "
                + "\n- ".join(schema_errors),
                "errors": schema_errors,
            }
        content = (
            f"# auth 段由探测账本机械注入（credential_ref={ref}，本会话实测），"
            "手写 auth 不被接受\n" + yaml.safe_dump(doc, allow_unicode=True, sort_keys=False)
        )
        if hit := _is_credential_violation(content):
            # 防御式（账本 snippet 只含 credential_ref 引用，正常不应触发）
            return {"error": f"安全红线：凭证明文（{hit}）"}
        rel = (Path("sut_configs") / name).as_posix()  # 裸名机械归位 sut_configs/
        self.staging[rel] = content
        return {
            "ok": True,
            "staged": rel,
            "auth_injected": {
                "credential_ref": ref,
                "url": fact["url"],
                "token_source": fact["token_source"],
                "note": "auth 段与实测账本逐字节一致——对账门禁必过，无需重新实测",
            },
        }

    async def validate_package(self) -> dict[str, Any]:
        """对暂存视图做物化校验（清单合法 + 资源目录 + 规则 YAML 可解析）。"""
        import yaml

        from agent_eval.packages import load_manifest

        errors: list[str] = []
        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp)
            view = self._view()
            if not view:
                return {"ok": False, "errors": ["包视图为空（无文件）"]}
            # 骨架开槽门禁（opt-in：暂存视图含 SKELETON.md 才检查——克隆/fork 既有包
            # 无骨架，行为不变）。开槽未闭 = 还有未验证的结论，落盘即把「未验证」
            # 固化成「已配置」（jxb 事故根因：探测期配置渐进成形，证据与幻觉同文件）。
            # 先于清单等结构检查——骨架是「改动计划」，计划未闭环先于一切结构问题
            if (skeleton := view.get(SKELETON_FILENAME)) is not None:
                errors += skeleton_gate_errors(skeleton)
            for rel, content in view.items():
                if content is None:  # 空内容/删除标记：不落盘
                    continue
                dest = tmp_root / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(content, encoding="utf-8")
            if not (tmp_root / MANIFEST_FILENAME).is_file():
                errors.append(f"缺少清单 {MANIFEST_FILENAME}")
                return {"ok": False, "errors": errors}  # 骨架开槽等先行检查的结论保留
            try:
                manifest = load_manifest(tmp_root)
            except Exception as e:  # noqa: BLE001 — 校验错误收集后交 Agent 自修复
                errors.append(f"清单校验失败: {e}")
                manifest = None
            # 资源目录按包形态判定（运行时真相，与 scenario validate 同源）：清单声明
            # default_task_set = 在线 SUT 形态，考卷来自 task_sets/、datasets 不参与
            # （内置 chat 包即无 datasets/）；未声明 = 离线文件形态，datasets/ 必需。
            # 在线形态 task_sets/ 同样必需（指南 §1）——缺失此前到运行时才炸
            required_dirs = ["rules", "prompts"]
            if manifest is not None and manifest.default_task_set is None:
                required_dirs.append("datasets")
            elif manifest is not None:
                required_dirs.append("task_sets")
            for sub in required_dirs:
                if not (tmp_root / sub).is_dir() or not any((tmp_root / sub).iterdir()):
                    errors.append(f"缺少资源目录或为空: {sub}/")
            # 约定：rules/ 与 prompts/ 的资产是 YAML（13 配置管理）——只写 .md 会被
            # 下游加载器静默忽略（实测 Agent 曾把提示词写成 README 式 .md）
            for sub in ("rules", "prompts"):
                if (tmp_root / sub).is_dir() and not any((tmp_root / sub).glob("*.yaml")):
                    errors.append(f"{sub}/ 缺少 YAML 资产（提示词/规则集须为 .yaml）")
            # 全量 YAML 解析门禁：包内**所有** .yaml/.yml（除清单——load_manifest
            # 已解析；除 sut_configs/——下方另有解析 + schema 校验）必须可解析。
            # 只扫 rules/ 时截断文件漏网（实测：task_sets/smoke.yaml 首写被截断，
            # 靠 Agent 自检 read_file 才发现——未自检即可带伤落盘）
            sut_prefix = "sut_configs/"
            for yf in sorted(
                [*tmp_root.rglob("*.yaml"), *tmp_root.rglob("*.yml")],
                key=lambda p: p.relative_to(tmp_root).as_posix(),
            ):
                rel_path = yf.relative_to(tmp_root).as_posix()
                if rel_path == MANIFEST_FILENAME or rel_path.startswith(sut_prefix):
                    continue
                try:
                    yaml.safe_load(yf.read_text(encoding="utf-8"))
                except yaml.YAMLError as e:
                    errors.append(
                        f"YAML 解析失败 {rel_path}: {e}——内容疑似被截断或损坏，"
                        "read_file 核对后整体重写"
                    )
            # 规则引用对账（evaluator 注册态 / prompt_id / dimension / stage）——悬空
            # 引用此前延迟到运行时才炸（实测：evaluator 写成 method 枚举值 llm_judge，
            # 10 条规则全被跳过 → 全 0 报告），落盘前以运行时同源真相（注册表）拦截
            from agent_eval.evaluation.rule_refs import check_rule_references

            errors += check_rule_references(tmp_root)
            # sut_configs 走执行器同款 schema 校验（未知键显式打回——执行器运行时
            # extra="allow" 会静默丢弃发明字段，落盘前必须拦截）
            from agent_eval.execution.registry import validate_sut_config_document

            sut_dir = tmp_root / "sut_configs"
            if sut_dir.is_dir():
                for sf in sorted([*sut_dir.glob("*.yaml"), *sut_dir.glob("*.yml")]):
                    try:
                        doc = yaml.safe_load(sf.read_text(encoding="utf-8"))
                    except yaml.YAMLError as e:
                        errors.append(f"sut_config YAML 解析失败 {sf.name}: {e}")
                        continue
                    errors += [
                        f"sut_config 校验失败 {sf.name}: {msg}"
                        for msg in validate_sut_config_document(doc)
                    ]
        return {"ok": not errors, "errors": errors}

    async def list_packages(self, source: str = "") -> dict[str, Any]:
        """列出全部已发现场景包（builtin/local/project 三源，PackageManager 同源发现）。

        「当前有哪些包」的机械真相源（与 CLI ``scenario list``、执行域选包同一
        枚举）——项目根（cwd）一级子目录含 agent_eval.yaml 的都算 project 包。
        只读无授权需求：包根 path 是发现元数据，读包内文件仍走分级授权
        （read_reference 按 ref 直读 / read_file 外部路径申请授权）。
        """
        from agent_eval.packages import PackageManager

        if source and source not in ("builtin", "local", "project"):
            return {"error": f"未知 source: {source}（可选 builtin / local / project，缺省全部）"}
        packages = [
            {
                "ref": pkg.manifest.ref,
                "source": pkg.source,
                "path": str(pkg.root),
                "name": pkg.manifest.name,
                "version": pkg.manifest.version,
                "description": truncate(pkg.manifest.description, 80),
                "editable": pkg.source != "builtin",
            }
            for pkg in PackageManager().list(source=source or None)
        ]
        notes = (
            "改已有 project/local 包首选原位编辑：退出本会话后 agent-eval scenario edit <ref>"
            "（或主菜单 2「场景包管理 → 用 Agent 修改选中的包」），会话根即包目录、原位生效。"
            "在本会话内 fork 改造须换新 scenario/id——沿用原 id 会在确认落盘归位 "
            "cwd/<id>-package/ 时与既有目录冲突。builtin 包只读，改造即 fork（scenario new）。"
            "读任意包内容用 read_reference（ref 取上面 ref 串的 scenario 或 scenario/id 段）。"
        )
        if not packages:
            notes = (
                "未发现任何场景包——确认项目根下存在 <id>-package/agent_eval.yaml，"
                "或用 scenario new 创建。"
            ) + notes
        return {"packages": packages, "total": len(packages), "notes": notes}

    async def search_reference(self, query: str) -> dict[str, Any]:
        """检索内置包（只读）匹配文件 + 方法论要点。"""
        from agent_eval.packages import PackageManager

        hits = []
        for pkg in PackageManager().list(source="builtin"):
            for p in sorted(pkg.root.rglob("*.yaml")):
                if query.lower() in p.relative_to(pkg.root).as_posix().lower():
                    hits.append(f"{pkg.manifest.ref}::{p.relative_to(pkg.root).as_posix()}")
        return {"query": query, "matched_files": hits[:20], "notes": _reference_notes()}

    async def read_reference(
        self, ref: str, path: str, max_chars: int = _DEFAULT_REFERENCE_CHARS
    ) -> dict[str, Any]:
        """只读已发现包（三源）的文件内容（Agent 参照真实格式的合法通道，免沙盒逃逸）。

        ref 走 PackageManager 解析（如 ``chat`` / 项目包 ``courseware/courseware-reasonableness``，
        可用 ref 见 list_packages）；path 限目标包根内。
        """
        from agent_eval.packages import PackageManager

        try:
            pkg = PackageManager().resolve_ref(ref)
        except Exception as e:  # noqa: BLE001 — 错误交 Agent 自修复
            return {"error": f"参考包不存在: {ref}（{e}；先 list_packages 查可用包）"}
        available = sorted(p.relative_to(pkg.root).as_posix() for p in pkg.root.rglob("*.yaml"))
        try:
            target = (pkg.root / path).resolve()
            if not target.is_relative_to(pkg.root.resolve()):
                raise ValueError(f"路径越出参考包根: {path}")
            content = target.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            return {
                "error": f"文件不存在或不可读: {ref}::{path}（{e}）",
                "available_files": available,
                "hint": "path 请原样取 available_files 中的相对路径重试",
            }
        except ValueError as e:
            return {"error": str(e)}
        rel = target.relative_to(pkg.root.resolve()).as_posix()
        return {"package": pkg.manifest.ref, "path": rel, "content": truncate(content, max_chars)}

    async def list_evaluators(self) -> dict[str, Any]:
        """当前真实可用的评估器注册 ID 清单（rules 的 evaluator 从此原样复制）。

        快照与运行时/落盘门禁**同一真相源**（rule_refs 的装载原语：内置注册 +
        包 entry_points）；暂存清单已声明 entry_points 时一并装载——草稿期声明的
        chat.* 等场景评估器同样可见，避免「清单已声明却被告知不可用」的假阴性
        （教训：校验/工具的真相源必须与运行时同源）。
        """
        from agent_eval.evaluation.evaluators.plugins import load_package_entry_points
        from agent_eval.evaluation.registry import registry
        from agent_eval.evaluation.rule_refs import _registered_evaluator_ids

        _registered_evaluator_ids(self.root)  # 内置 + 磁盘清单 entry_points（幂等）
        if staged := self.staging.get(MANIFEST_FILENAME):
            with tempfile.TemporaryDirectory() as tmp:
                (Path(tmp) / MANIFEST_FILENAME).write_text(staged, encoding="utf-8")
                load_package_entry_points(tmp)  # 草稿未落盘的 entry_points 同样装入
        evaluators = sorted(registry.list_registered())
        # 判官模板变量契约（copy, don't recall 的变量面）：评估器类级 prompt_variables
        # 声明的实时快照——user_prompt_template 的变量从此原样复制，与落盘门禁同源
        # （契约表文档是副本，真相源在这里与评估器类声明）
        contracts = {
            eid: sorted(contract)
            for eid in evaluators
            if (cls := registry.class_of(eid)) is not None
            and (contract := getattr(cls, "prompt_variables", None)) is not None
        }
        note = (
            "rules 的 evaluator 字段必须从此清单**原样复制**——它是评估器注册 ID，"
            "不是 method 枚举值（llm_judge/llm 不是 ID）；清单含本包 entry_points "
            "声明的场景评估器（如 chat.*）"
        )
        if contracts:
            note += (
                "；prompt_variables 是各评估器判官模板（user_prompt_template）可用的"
                "变量清单，同样**原样复制**勿臆造（写错运行时报「模板渲染失败，变量缺失」）"
            )
        return {"evaluators": evaluators, "prompt_variables": contracts, "note": note}

    async def preview_diff(self) -> dict[str, Any]:
        """暂存 vs 磁盘的统一 diff（与宿主确认界面同源）。"""
        if not self.staging:
            return {
                "diff": "",
                "changed": 0,
                "note": "暂存区为空：先用 write_file/delete_file 产生变更再预览",
            }
        return {"diff": self.render_diff(), "changed": len(self.staging)}

    # ─── 宿主侧（不经 Agent） ─────────────────────────────────────

    def render_diff(self) -> str:
        parts: list[str] = []
        for rel in sorted(self.staging):
            new = self.staging[rel]
            old = self._disk_text(self._resolve_in(rel)) if (self.root / rel).is_file() else None
            if new is None:
                parts.append(f"--- {rel}\n+++ /dev/null\n-（删除文件）")
                continue
            old_lines = (old or "").splitlines(keepends=True)
            new_lines = new.splitlines(keepends=True)
            diff = "".join(difflib.unified_diff(old_lines, new_lines, fromfile=rel, tofile=rel))
            parts.append(diff or f"{rel}（无变化）")
        return "\n".join(parts)

    def staged_manifest_id(self) -> str | None:
        """暂存视图中的清单 id（无清单/解析失败返回 None）——归位预告用。"""
        import yaml

        text = self._view().get(MANIFEST_FILENAME)
        if not text:
            return None
        try:
            data = yaml.safe_load(text) or {}
            return str((data.get("package") or {}).get("id") or "") or None
        except yaml.YAMLError:
            return None

    @property
    def has_staged_changes(self) -> bool:
        return bool(self.staging)

    def reset_staging(self) -> None:
        self.staging.clear()

    def commit(self) -> list[str]:
        """原子提交暂存到磁盘（宿主在确认+校验通过后调用），返回变更清单。

        SKELETON.md 排除在外：骨架是过程产物（探测事实与证据链），落进包根会随
        归位混入最终包——从暂存摘除，最新文本留在 :attr:`skeleton_archive` 供宿主
        归档为审计产物（WorkbenchAgent 落会话区）。
        """
        changed: list[str] = []
        # 先全部物化到临时目录再原子替换内容，失败中途不产生半提交视图
        for rel, new in sorted(self.staging.items()):
            if rel == SKELETON_FILENAME:
                self.staging.pop(rel)
                self.skeleton_archive = new
                changed.append(f"S {rel}（骨架：过程产物不入包，已留档）")
                continue
            abs_path = self._resolve_in(rel)
            if new is None:
                if abs_path.is_file():
                    abs_path.unlink()
                changed.append(f"D {rel}")
                continue
            abs_path.parent.mkdir(parents=True, exist_ok=True)
            abs_path.write_text(new, encoding="utf-8")
            changed.append(f"M {rel}")
        self.staging.clear()
        return changed

    def export_staging_snapshot(self) -> dict[str, Any]:
        """导出进度快照（跨进程续作源，SessionStore 每轮随写）。

        只含可序列化的进度态：暂存文件文本 + 骨架留档（commit 摘除前不可丢）。
        不含凭证域——探测账本的 session_tokens 等凭证态由 SUTProbeToolServer
        .ledger_snapshot 另行导出，且同样只含事实（无凭证值）。
        """
        return {
            "root": str(self.root),
            "staging": self.staging,
            "skeleton_archive": self.skeleton_archive,
        }

    def import_staging_snapshot(self, payload: Any) -> int:
        """恢复暂存与骨架留档，返回恢复的暂存条数（类型不符静默忽略单条）。

        skeleton_archive 仅在当前为空时采纳——本会话已更新的留档优先。
        """
        if not isinstance(payload, dict):
            return 0
        staging = payload.get("staging")
        if isinstance(staging, dict):
            self.staging = {
                rel: content
                for rel, content in staging.items()
                if isinstance(rel, str) and (content is None or isinstance(content, str))
            }
        if self.skeleton_archive is None and isinstance(payload.get("skeleton_archive"), str):
            self.skeleton_archive = payload["skeleton_archive"]
        return len(self.staging)


def materialize_view(pkg_root: Path, server: PackageToolServer, dest: Path) -> Path:
    """把磁盘包 + 暂存覆盖物化到 dest（校验/测试辅助；不改动原包）。"""
    view = server._view()  # 宿主侧辅助（同包内）
    shutil.rmtree(dest, ignore_errors=True)
    for rel, content in view.items():
        if content is None:  # 空内容/删除标记：不落盘（rmtree 后即删除语义）
            continue
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return dest
