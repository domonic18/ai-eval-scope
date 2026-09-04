"""规则集引用完整性校验（双端共享：staging ``validate_package`` + ``scenario validate``）。

实测事故（2026-09-03，agent-security 包）：guide 最小示例把 method 枚举值
``llm_judge`` 写进 ``evaluator`` 字段（该字段语义是评估器**注册 ID**），Agent 照抄
→ 运行时 10 条规则全部「未注册的评估器」被跳过 → 0 评估器产出全 0 报告。双端
校验此前只查 YAML 可解析、不查引用——悬空引用全部延迟到运行时才炸。本模块把
引用对账提前到落盘前，与 ``validate_sut_config_document`` 同一哲学：**校验的
真相源即运行时真相源**（评估器注册表 + 包内 prompts/dimensions/cascade）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def _registry_ready(pkg_root: Path) -> Any:
    """运行时同源的注册表：内置注册 + 本包 entry_points 装载。

    与引擎评估前完全同款（``import agent_eval.evaluation.evaluators`` 触发内置
    ``@registry.register``，``load_package_entry_points`` 导入包声明的评估器模块）——
    少装包 entry_points 会把「清单已声明、运行时可用」的 ID 误判为未注册
    （假阴性，实测 agent-security 包声明了 chat entry_points 却被打回）。
    """
    import agent_eval.evaluation.evaluators  # noqa: F401 — 导入触发装饰器注册
    from agent_eval.evaluation.evaluators.plugins import load_package_entry_points
    from agent_eval.evaluation.registry import registry

    load_package_entry_points(pkg_root)
    return registry


def _registered_evaluator_ids(pkg_root: Path) -> list[str]:
    """评估器注册 ID 快照（列表视图，``list_evaluators`` 工具与错误消息共用）。"""
    return _registry_ready(pkg_root).list_registered()


def _load_yaml(path: Path) -> Any:
    """解析单个 YAML；失败返回 None（解析错误由调用方的既有检查报告，此处不重复）。"""
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 — 交给调用方已存在的 YAML 解析检查
        return None


def _prompt_template_vars(root: Path) -> dict[str, set[str]]:
    """判官模板 template_id → 未声明变量集（jinja2 语义，与执行侧 StrictUndefined 同源）。

    实测事故（agent-security 包）：判官模板写 ``{{ response }}`` 而评估器只注入
    ``content/instruction/must_mention`` → 运行时 10 规则全报「模板渲染失败，
    变量缺失: 'response' is undefined」→ 全 0 报告。模板变量是机械契约，落盘
    前即可对账。解析失败跳过（语法错误交运行时报）。
    """
    try:
        from jinja2 import Environment, meta
    except ImportError:  # noqa: BLE001 — jinja2 缺席时跳过该检查（运行时仍会报）
        return {}
    env = Environment()
    out: dict[str, set[str]] = {}
    for p in sorted([*root.glob("prompts/*.yaml"), *root.glob("prompts/*.yml")]):
        doc = _load_yaml(p)
        if not isinstance(doc, dict) or not (tid := doc.get("template_id")):
            continue
        tpl = doc.get("user_prompt_template")
        if isinstance(tpl, str) and tpl.strip():
            try:
                out[str(tid)] = set(meta.find_undeclared_variables(env.parse(tpl)))
            except Exception:  # noqa: BLE001 — 模板语法错误不在此处定性
                continue
    return out


def check_rule_references(pkg_root: Path | str) -> list[str]:
    """校验包内规则集的全部引用可解析：evaluator 注册态 / prompt_id / dimension / stage。

    返回人类可读错误清单（空 = 通过）。只校验 ``enabled`` 不为 false 的规则——与
    运行时 ``build_pipeline_config`` 的跳过语义一致，避免对不生效规则报噪音。
    """
    root = Path(pkg_root)
    registry = _registry_ready(root)
    registered = registry.list_registered()
    prompt_ids = {
        pid
        for p in sorted([*root.glob("prompts/*.yaml"), *root.glob("prompts/*.yml")])
        if isinstance(doc := _load_yaml(p), dict) and (pid := doc.get("template_id"))
    }
    template_vars = _prompt_template_vars(root)

    errors: list[str] = []
    # 判官模板级采样次数（num_samples）防呆：声明时必须为 ≥1 的整数——0/负数运行时
    # 炸出难懂的「no median for empty data」（该规则 0 分），落盘前拦截（缺省 3，
    # 成本敏感场景设 1）
    for p in sorted([*root.glob("prompts/*.yaml"), *root.glob("prompts/*.yml")]):
        doc = _load_yaml(p)
        if not isinstance(doc, dict) or "num_samples" not in doc:
            continue
        n = doc["num_samples"]
        if not isinstance(n, int) or isinstance(n, bool) or n < 1:
            errors.append(
                f"{p.name}: num_samples 必须为 ≥1 的整数（收到 {n!r}）——该字段决定判官对"
                "每条规则独立采样的次数（各维度取中位数，缺省 3；成本敏感场景设 1）"
            )
    for rf in sorted([*root.glob("rules/*.yaml"), *root.glob("rules/*.yml")]):
        doc = _load_yaml(rf)
        if not isinstance(doc, dict):
            continue
        dim_ids = {d.get("id") for d in doc.get("dimensions") or [] if isinstance(d, dict)}
        stage_ids = {c.get("stage") for c in doc.get("cascade") or [] if isinstance(c, dict)}
        for rule in doc.get("rules") or []:
            if not isinstance(rule, dict) or rule.get("enabled") is False:
                continue
            rid = rule.get("id", "?")
            evaluator = rule.get("evaluator")
            if evaluator and evaluator not in registered:
                errors.append(
                    f"{rf.name} 规则 {rid}: evaluator {evaluator!r} 未注册——该字段是评估器"
                    "注册 ID 而非 method（llm_judge/llm 是 method 取值，写在这里运行时必报"
                    f"「未注册的评估器」）。可用 ID: {registered}；chat.* 等场景评估器需"
                    "包清单 entry_points.evaluators 声明（参照 chat 包）"
                )
            # 判官模板对账：有效模板 = 规则 prompt_id（声明时），否则回退评估器类默认
            # template_id。有效模板必须存在于包 prompts/（缺失运行时报「未找到 Prompt
            # 模板」）；评估器声明了变量契约（prompt_variables）时，模板变量不得越界
            # （越界运行时 StrictUndefined 报「模板渲染失败，变量缺失」）——两种错该
            # 规则都直接 0 分（实测 agent-security 包 {{ response }} 事故）
            evaluator_cls = (
                registry.class_of(evaluator) if evaluator and evaluator in registered else None
            )
            contract = getattr(evaluator_cls, "prompt_variables", None) if evaluator_cls else None
            effective_pid: str | None = None
            if pid := rule.get("prompt_id"):
                if pid not in prompt_ids:
                    errors.append(
                        f"{rf.name} 规则 {rid}: prompt_id {pid!r} 在 prompts/ 中不存在"
                        f"（可用 template_id: {sorted(prompt_ids) or '无'}）"
                    )
                else:
                    effective_pid = str(pid)
            elif evaluator_cls is not None:
                fallback = getattr(evaluator_cls, "template_id", None)
                if isinstance(fallback, str) and fallback:
                    if fallback in prompt_ids:
                        effective_pid = fallback
                    else:
                        errors.append(
                            f"{rf.name} 规则 {rid}: 未声明 prompt_id，运行时回退评估器 "
                            f"{evaluator!r} 的默认模板 {fallback!r}，但包 prompts/ 中不存在——"
                            "运行时必报「未找到 Prompt 模板」该规则 0 分（从参照包复制该"
                            "模板，或显式声明 prompt_id 指向已有模板）"
                        )
            if effective_pid and contract:
                stray = template_vars.get(effective_pid, set()) - set(contract)
                if stray:
                    errors.append(
                        f"{rf.name} 规则 {rid}: 判官模板 {effective_pid!r} 使用了评估器 "
                        f"{evaluator!r} 不注入的变量 {sorted(stray)}——模板变量只能用 "
                        f"{sorted(contract)}（写错运行时必报「模板渲染失败，变量缺失」，"
                        "该规则直接 0 分）"
                    )
            if dim := rule.get("dimension"):
                if dim not in dim_ids:
                    errors.append(f"{rf.name} 规则 {rid}: dimension {dim!r} 未在 dimensions[] 声明")
            if stage := rule.get("stage"):
                if stage not in stage_ids:
                    errors.append(f"{rf.name} 规则 {rid}: stage {stage!r} 未在 cascade[] 声明")
    return errors


__all__ = ["check_rule_references"]
