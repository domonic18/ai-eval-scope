"""结构化输出解析器 — 从 LLM 响应中提取 JSON 并验证 Schema。"""

from __future__ import annotations

import json
import re
from typing import Any

import jsonschema

from agent_eval.config import STRUCTURED_OUTPUT_DEFAULTS
from agent_eval.core.exceptions import LLMResponseError


class StructuredOutputParser:
    """从 LLM 响应中提取 JSON 并验证 Schema。

    策略：
    1. 从 LLM 响应文本中提取 JSON 块
    2. 使用 jsonschema 验证提取的 JSON
    3. 不符合时抛出 LLMResponseError
    """

    def __init__(self, max_retries: int = STRUCTURED_OUTPUT_DEFAULTS.max_retries) -> None:
        """初始化解析器。

        Args:
            max_retries: 最大重试次数（用于外部重试逻辑）。
        """
        self.max_retries = max_retries

    def parse(self, raw_response: str, schema: dict[str, Any]) -> dict[str, Any]:
        """提取 JSON 并验证 Schema。

        Args:
            raw_response: LLM 原始响应文本。
            schema: JSON Schema 用于验证。

        Returns:
            解析后的字典。

        Raises:
            LLMResponseError: JSON 提取失败或 Schema 验证失败。
        """
        if not raw_response or not raw_response.strip():
            raise LLMResponseError("LLM 响应为空，无法解析 JSON")

        json_str = self._extract_json(raw_response)

        try:
            data = json.loads(json_str)
        except json.JSONDecodeError as e:
            raise LLMResponseError(
                f"JSON 解析失败: {e}",
                details={"raw_response": raw_response[:200]},
            ) from e

        self._validate_schema(data, schema)
        return data

    def _extract_json(self, text: str) -> str:
        """从文本中提取 JSON 块。

        支持格式：
        - ```json ... ``` 包裹
        - ``` ... ``` 包裹
        - 裸 JSON 对象/数组
        """
        text = text.strip()

        # 尝试匹配 ```json ... ``` 代码块
        match = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", text, re.DOTALL)
        if match:
            return match.group(1).strip()

        # 尝试匹配裸 JSON 对象
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            return match.group(0)

        # 尝试匹配裸 JSON 数组
        match = re.search(r"\[.*\]", text, re.DOTALL)
        if match:
            return match.group(0)

        raise LLMResponseError(
            "无法从 LLM 响应中提取 JSON",
            details={"raw_response": text[:200]},
        )

    def _validate_schema(self, data: dict[str, Any], schema: dict[str, Any]) -> None:
        """使用 jsonschema 验证数据。

        Args:
            data: 待验证的数据。
            schema: JSON Schema。

        Raises:
            LLMResponseError: Schema 验证失败。
        """
        if not schema:
            return  # 空 Schema 跳过验证

        try:
            jsonschema.validate(data, schema)
        except jsonschema.ValidationError as e:
            raise LLMResponseError(
                f"JSON Schema 验证失败: {e.message}",
                details={"path": list(e.absolute_path), "value": e.instance},
            ) from e
