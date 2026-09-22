"""PackageToolServer 清单与 SUT 配置工具 mixin — read/update_manifest、write_sut_config、validate_package。

Agent 可调用；错误以 ``{"error": ...}`` 返回值交 Agent 自修复（不中断图）。
仅供 ``tools.PackageToolServer`` 组合，不独立使用。
"""

from __future__ import annotations

import tempfile
from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import Any

from agent_eval.agent.workbench.tools_shared import (
    SKELETON_FILENAME,
    _is_credential_violation,
    skeleton_gate_errors,
)
from agent_eval.packages import MANIFEST_FILENAME


class ManifestToolsMixin:
    """包清单读写 + SUT 配置机械物化 + 暂存视图整体校验（组合用 mixin）。"""

    # 组合主体成员声明（仅注解，零运行时）——供类型检查器解析 self.* 引用
    staging: dict[str, str | None]
    ledger: Any
    read_file: Callable[..., Coroutine[Any, Any, dict[str, Any]]]
    write_file: Callable[..., Coroutine[Any, Any, dict[str, Any]]]
    _view: Callable[..., dict[str, str]]

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
