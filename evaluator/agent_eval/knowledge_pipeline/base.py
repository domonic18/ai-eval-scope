"""知识点完善管道抽象基类。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, ClassVar

from agent_eval.knowledge_pipeline.models import ExtractedBatch, Question


class DataSource(ABC):
    """数据源抽象基类。

    用 ``kind`` 属性区分两类源：
    - ``"questions"``：评测题数据集（arc/cmmlu），``read()`` 返回 ``list[Question]``
    - ``"raw_items"``：结构化数值表（周期表 JSON/NIST），``read()`` 返回 ``list[dict]``
    """

    kind: ClassVar[str]  # "questions" 或 "raw_items"

    @abstractmethod
    def read(
        self, limit: int | None = None, **kwargs: Any
    ) -> list[Question] | list[dict[str, Any]]:
        """读取数据源。

        Returns:
            kind="questions" 时返回 list[Question]；
            kind="raw_items" 时返回 list[dict]（原始结构化数据）。
        """


class Extractor(ABC):
    """LLM 提取器抽象基类（消费 questions）。"""

    field: ClassVar[str]  # "misconceptions" / "constants"

    @abstractmethod
    def extract(self, questions: list[Question], **kwargs: Any) -> ExtractedBatch:
        """从评测题列表提取知识点。

        内部调用 LLM（复用 LLMClientFactory + client.chat）。
        """


class Converter(ABC):
    """结构化转换器抽象基类（消费 raw_items）。"""

    field: ClassVar[str]  # "constants" / "domain_facts"

    @abstractmethod
    def convert(self, raw_items: list[dict[str, Any]], **kwargs: Any) -> ExtractedBatch:
        """从结构化数据转换知识点（纯数据转换，无 LLM）。

        如：周期表 JSON → constants（Kelvin→℃，符号→中文映射）。
        """
