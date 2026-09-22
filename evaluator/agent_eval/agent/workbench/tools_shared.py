"""场景包工具面共享常量与纯函数（tools*.py 各模块共用）。

无状态件：写入白名单 / 凭证红线判定 / 骨架开槽门禁 / 截断缺省——
不依赖 server 实例（PackageManager 查询惰性导入）。
"""

from __future__ import annotations

import re
from pathlib import Path

from agent_eval.config.paths import PACKAGE_ROOT

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
