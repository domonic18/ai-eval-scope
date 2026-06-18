"""评估器注册中心 — EvaluatorRegistry。

借鉴 OpenCompass 的装饰器注册模式，支持 @registry.register(id) 注册，
通过 registry.create(id, params) 工厂创建实例。
"""

from __future__ import annotations

from typing import Any

from agent_eval.core.exceptions import EvaluatorNotFoundError
from agent_eval.evaluation.base import BaseEvaluator


class EvaluatorRegistry:
    """评估器注册中心。

    使用装饰器模式注册评估器类，通过工厂方法创建实例。

    示例:
        registry = EvaluatorRegistry()

        @registry.register("format.response_format")
        class ResponseFormatEvaluator(BaseEvaluator):
            ...

        evaluator = registry.create("format.response_format", {"allowed_formats": ["md"]})
    """

    def __init__(self) -> None:
        self._registry: dict[str, type[BaseEvaluator]] = {}

    def register(self, evaluator_id: str):
        """装饰器：注册评估器类。

        Args:
            evaluator_id: 评估器唯一标识。

        Returns:
            装饰器函数。
        """

        def decorator(cls: type[BaseEvaluator]) -> type[BaseEvaluator]:
            if evaluator_id in self._registry:
                raise ValueError(
                    f"评估器 ID 冲突: {evaluator_id} 已注册为 {self._registry[evaluator_id].__name__}"
                )
            self._registry[evaluator_id] = cls
            return cls

        return decorator

    def create(self, evaluator_id: str, params: dict[str, Any] | None = None) -> BaseEvaluator:
        """工厂方法：根据 ID 创建评估器实例。

        Args:
            evaluator_id: 评估器唯一标识。
            params: 评估器参数（可选）。

        Returns:
            配置好的评估器实例。

        Raises:
            EvaluatorNotFoundError: 评估器 ID 未注册。
        """
        if evaluator_id not in self._registry:
            raise EvaluatorNotFoundError(evaluator_id, available=list(self._registry.keys()))
        evaluator = self._registry[evaluator_id]()
        if params:
            evaluator.setup(params)
        return evaluator

    def is_registered(self, evaluator_id: str) -> bool:
        """检查评估器是否已注册。"""
        return evaluator_id in self._registry

    def list_registered(self) -> list[str]:
        """列出所有已注册的评估器 ID。"""
        return sorted(self._registry.keys())

    def get_evaluator_class(self, evaluator_id: str) -> type[BaseEvaluator] | None:
        """获取评估器类（不实例化）。"""
        return self._registry.get(evaluator_id)

    def unregister(self, evaluator_id: str) -> bool:
        """注销指定评估器（主要用于测试清理）。

        Returns:
            是否成功注销。
        """
        if evaluator_id in self._registry:
            del self._registry[evaluator_id]
            return True
        return False


# 全局单例
registry = EvaluatorRegistry()
