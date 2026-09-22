"""常识评估器共享设施 — 文本收集、事实知识库缓存、算术求值。

info_accuracy 与 logical_consistency 共用的模块级 helper 集中于此；
评估器类定义在同包各模块，经包 ``__init__`` 导入触发注册。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import structlog

from agent_eval.evaluation.text_utils import (
    collect_file_texts,
    collect_text_content_with_markers,
)

logger = structlog.get_logger("evaluation.commonsense")

# fact_verdict 二次确认的单批最大候选数（超过则分批调用，避免单次 prompt 过大
# 导致 LLM 调用失败，如数学样本 98 候选一次调用即失败）
FACT_VERDICT_BATCH_SIZE = 20


def _collect_text_content(output_dir: Path) -> str:
    """收集目录下所有文档的文本内容（带文件边界标记，合并为单字符串）。

    logical_consistency 使用：判官读到 `=== FILE: 相对路径 ===` 标记后，可在 issue
    的 involved_files 引用具体文件名。
    """
    return collect_text_content_with_markers(output_dir)


def _collect_file_names(output_dir: Path) -> list[str]:
    """收集目录下所有文档文件名。"""
    names: list[str] = []
    for ext in ("*.md", "*.markdown", "*.html", "*.htm"):
        for f in output_dir.rglob(ext):
            names.append(f.name)
    return sorted(names)


def _collect_file_texts(output_dir: Path) -> dict[str, str]:
    """收集 per-file 文本内容，保留文件归属。

    Returns:
        {文件相对路径: 纯文本内容}，HTML 经 `text_utils` 干净提取。
    """
    return collect_file_texts(output_dir)


# ─── 事实知识库（委托给 KnowledgeBaseManager） ───

_knowledge_manager = None


def _get_knowledge_manager() -> Any:
    """获取默认 KnowledgeBaseManager 单例。"""
    global _knowledge_manager
    if _knowledge_manager is None:
        from agent_eval.knowledge.manager import KnowledgeBaseManager

        _knowledge_manager = KnowledgeBaseManager()
    return _knowledge_manager


def _load_fact_db(subjects: list[str] | None = None) -> dict:
    """加载事实知识库（兼容旧接口，委托给 KnowledgeBaseManager）。"""
    fact_db: dict = _get_knowledge_manager().load(subjects)
    return fact_db


def _reset_fact_db_cache() -> None:
    """重置事实知识库缓存（兼容旧接口）。"""
    _get_knowledge_manager().invalidate_cache()


# ─── 算术表达式求值 ───

# 算术运算符集合
_OP_CHARS = set("+＋-－×÷*/")


def _eval_simple_expr(expr: str) -> float | None:
    """求值简单算术表达式（支持 +,-,×,÷ 及运算符优先级）。

    支持形如 ``28×8 + 22×9 + 35×4`` 的多项表达式。
    返回浮点结果，解析失败返回 None。
    """
    # 归一化运算符
    norm = expr.replace("＋", "+").replace("－", "-").replace("×", "*").replace("÷", "/")
    # 词法分析：提取 数字 / 运算符
    tokens: list[str | float] = []
    for m in re.finditer(r"(\d+\.?\d*)|([+\-*/])", norm):
        num_s, op_s = m.group(1), m.group(2)
        if num_s:
            tokens.append(float(num_s))
        elif op_s:
            tokens.append(op_s)

    if not tokens or not isinstance(tokens[0], float):
        return None

    # 分离数字和运算符
    numbers: list[float] = []
    ops: list[str] = []
    for t in tokens:
        if isinstance(t, float):
            numbers.append(t)
        else:
            ops.append(t)

    if len(numbers) != len(ops) + 1 or not numbers:
        return None

    # 第一遍：处理 * / （高优先级）
    i = 0
    while i < len(ops):
        if ops[i] in ("*", "/"):
            if ops[i] == "*":
                numbers[i] *= numbers[i + 1]
            else:
                if numbers[i + 1] == 0:
                    return None
                numbers[i] /= numbers[i + 1]
            numbers.pop(i + 1)
            ops.pop(i)
        else:
            i += 1

    # 第二遍：处理 + -
    result = numbers[0]
    for i, op in enumerate(ops):
        if op == "+":
            result += numbers[i + 1]
        elif op == "-":
            result -= numbers[i + 1]
        else:
            return None  # 不应到这里

    return result


# 竖式计算上下文关键词（出现在算式附近则跳过该算式）
_VERTICAL_CALC_KEYWORDS = re.compile(r"[写记进退]\d|[进退]一当十|满十进一|个位|十位|百位")
