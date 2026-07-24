"""场景化指标的安全表达式求值器。

使用 Python ``ast`` 模块做白名单求值，禁止任意属性访问 / 调用 / 导入，
杜绝任意代码执行。仅放行算术、比较、布尔运算、字面量与一组显式注册的函数。

表达式方言（扁平数组，避免嵌套点访问的歧义）：
- ``total``：样本总数（int）
- 样本过程字段数组：``reward`` / ``total_duration_ms`` / ``llm_calls`` / ``token_usage``
- 场景化样本指标数组：``stage_metrics`` 的每个 key（如 courseware 下的 ``soft`` / ``pref``）
- ``<stage_id>_gate``：该阶段门控通过的布尔数组
- 函数：``mean`` / ``count`` / ``sum`` / ``min`` / ``max`` / ``len`` / ``abs`` /
  ``both`` / ``all`` / ``any`` / ``gated_mean``
"""

from __future__ import annotations

import ast
import operator
from collections.abc import Callable
from typing import Any

from agent_eval.core.exceptions import ScenarioExpressionError

_BIN_OPS: dict[type, Callable[[Any, Any], Any]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}

_UNARY_OPS: dict[type, Callable[[Any], Any]] = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
    ast.Not: operator.not_,
}

_CMPS: dict[type, Callable[[Any, Any], bool]] = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
}


def _mean(xs: list[Any]) -> float:
    xs = list(xs)
    return sum(xs) / len(xs) if xs else 0.0


def _count(xs: Any) -> int:
    """统计真值个数（用于布尔门控数组）。"""
    return sum(1 for x in xs if x)


def _both(xs: Any, ys: Any) -> list[bool]:
    """两个等长布尔数组的逐元素与。"""
    return [bool(x) and bool(y) for x, y in zip(xs, ys, strict=False)]


def _gated_mean(values: Any, *gates: Any) -> float:
    """对「所有门控数组同时为真」的样本取 values 均值；无样本时返回 0.0。"""
    selected = [v for v, *gs in zip(values, *gates, strict=False) if gs and all(gs)]
    return sum(selected) / len(selected) if selected else 0.0


_ALLOWED_FUNCS: dict[str, Callable[..., Any]] = {
    "mean": _mean,
    "count": _count,
    "sum": lambda xs: sum(xs),
    "min": lambda xs: min(xs) if xs else 0.0,
    "max": lambda xs: max(xs) if xs else 0.0,
    "len": lambda xs: len(xs),
    "abs": abs,
    "round": round,
    "both": _both,
    "all": all,
    "any": any,
    "gated_mean": _gated_mean,
}


class _SafeEvaluator(ast.NodeVisitor):
    """AST 白名单求值器。"""

    def __init__(self, context: dict[str, Any]) -> None:
        self.ctx = context

    def evaluate(self, expression: str) -> Any:
        try:
            tree = ast.parse(expression, mode="eval")
        except SyntaxError as e:
            raise ScenarioExpressionError(
                f"指标表达式语法错误: {expression!r}", details={"error": str(e)}
            ) from e
        return self.visit(tree.body)

    def visit(self, node: ast.AST) -> Any:  # type: ignore[override]
        method = getattr(self, f"visit_{type(node).__name__}", None)
        if method is None:
            raise ScenarioExpressionError(
                f"表达式包含不支持的语法节点: {type(node).__name__}",
                details={"node": ast.dump(node)},
            )
        return method(node)

    def visit_Constant(self, node: ast.Constant) -> Any:
        return node.value

    def visit_Name(self, node: ast.Name) -> Any:
        if node.id in _ALLOWED_FUNCS:
            return _ALLOWED_FUNCS[node.id]
        if node.id in self.ctx:
            return self.ctx[node.id]
        raise ScenarioExpressionError(
            f"指标表达式引用了未知变量: {node.id}",
            details={"available": sorted(self.ctx.keys() | _ALLOWED_FUNCS.keys())},
        )

    def visit_BinOp(self, node: ast.BinOp) -> Any:
        op = _BIN_OPS.get(type(node.op))
        if op is None:
            raise ScenarioExpressionError(f"不支持的二元运算: {type(node.op).__name__}")
        return op(self.visit(node.left), self.visit(node.right))

    def visit_UnaryOp(self, node: ast.UnaryOp) -> Any:
        op = _UNARY_OPS.get(type(node.op))
        if op is None:
            raise ScenarioExpressionError(f"不支持的一元运算: {type(node.op).__name__}")
        return op(self.visit(node.operand))

    def visit_BoolOp(self, node: ast.BoolOp) -> Any:
        values = [self.visit(v) for v in node.values]
        if isinstance(node.op, ast.And):
            result: Any = True
            for v in values:
                result = result and v
                if not result:
                    break
            return result
        # Or
        result = False
        for v in values:
            result = result or v
            if result:
                break
        return result

    def visit_Compare(self, node: ast.Compare) -> Any:
        left = self.visit(node.left)
        for op_node, right_node in zip(node.ops, node.comparators, strict=False):
            op = _CMPS.get(type(op_node))
            if op is None:
                raise ScenarioExpressionError(f"不支持的比较运算: {type(op_node).__name__}")
            right = self.visit(right_node)
            if not op(left, right):
                return False
            left = right
        return True

    def visit_IfExp(self, node: ast.IfExp) -> Any:
        if self.visit(node.test):
            return self.visit(node.body)
        return self.visit(node.orelse)

    def visit_List(self, node: ast.List) -> list[Any]:
        return [self.visit(e) for e in node.elts]

    def visit_Tuple(self, node: ast.Tuple) -> tuple[Any, ...]:
        return tuple(self.visit(e) for e in node.elts)

    def visit_Subscript(self, node: ast.Subscript) -> Any:
        value = self.visit(node.value)
        return value[self.visit(node.slice)]

    def visit_Call(self, node: ast.Call) -> Any:
        func = self.visit(node.func)
        if not callable(func):
            raise ScenarioExpressionError("表达式调用了不可调用对象")
        if node.keywords:
            raise ScenarioExpressionError("指标表达式不允许使用关键字参数")
        args = [self.visit(a) for a in node.args]
        return func(*args)


def safe_eval(expression: str, context: dict[str, Any]) -> float:
    """在给定上下文中安全求值，返回 float。"""
    result = _SafeEvaluator(context).evaluate(expression)
    try:
        return float(result)
    except (TypeError, ValueError) as e:
        raise ScenarioExpressionError(
            f"指标表达式结果无法转为数值: {expression!r}",
            details={"result": repr(result)},
        ) from e
