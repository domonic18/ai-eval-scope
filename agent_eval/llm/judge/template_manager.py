"""Prompt 模板管理器 — 从文件系统加载和渲染 Prompt 评估模板。"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import jinja2
import structlog
import yaml

from agent_eval.core.exceptions import LLMError

logger = structlog.get_logger("template_manager")


@dataclass
class JudgeDimension:
    """评分维度。"""

    dim_id: str
    name: str
    description: str
    weight: float = 1.0
    score_range: tuple[float, float] = (0.0, 10.0)


@dataclass
class JudgeTemplate:
    """LLM 评审 Prompt 模板。"""

    template_id: str
    name: str
    dimensions: list[JudgeDimension] = field(default_factory=list)
    system_prompt: str = ""
    user_prompt_template: str = ""
    output_schema: dict[str, Any] = field(default_factory=dict)
    temperature: float = 0.0
    seed: int = 42
    num_samples: int = 3


class TemplateManager:
    """从文件系统加载和管理 Prompt 评估模板。

    模板为 YAML 文件，每个文件定义一个 JudgeTemplate。
    用户提示模板使用 Jinja2 渲染变量替换。
    """

    def __init__(self, template_dir: Path | str) -> None:
        """初始化模板管理器。

        Args:
            template_dir: 模板文件目录路径。
        """
        self._template_dir = Path(template_dir)
        self._templates: dict[str, JudgeTemplate] = {}
        self._jinja_env = jinja2.Environment(undefined=jinja2.StrictUndefined)

    def load_all(self) -> None:
        """加载目录下所有 YAML 模板文件。"""
        if not self._template_dir.exists():
            logger.warning(
                "模板目录不存在，LLM 评估器将无法加载 Prompt",
                path=str(self._template_dir),
            )
            return
        for path in self._template_dir.glob("*.yaml"):
            self._load_template(path)
        for path in self._template_dir.glob("*.yml"):
            self._load_template(path)

    def get(self, template_id: str) -> JudgeTemplate:
        """获取指定模板。

        Args:
            template_id: 模板 ID。

        Returns:
            JudgeTemplate 实例。

        Raises:
            LLMError: 模板不存在时。
        """
        if template_id not in self._templates:
            raise LLMError(
                f"未找到 Prompt 模板: {template_id}",
                details={
                    "template_id": template_id,
                    "available": list(self._templates.keys()),
                },
            )
        return self._templates[template_id]

    def render(self, template_id: str, variables: dict[str, Any]) -> tuple[str, str]:
        """渲染模板，返回 (system_prompt, user_prompt)。

        Args:
            template_id: 模板 ID。
            variables: Jinja2 变量字典。

        Returns:
            (system_prompt, user_prompt) 元组。

        Raises:
            LLMError: 模板不存在或变量缺失时。
        """
        template = self.get(template_id)
        try:
            jinja_template = self._jinja_env.from_string(template.user_prompt_template)
            user_prompt = jinja_template.render(**variables)
        except jinja2.UndefinedError as e:
            raise LLMError(
                f"模板渲染失败，变量缺失: {e}",
                details={"template_id": template_id},
            ) from e
        return template.system_prompt, user_prompt

    @property
    def template_ids(self) -> list[str]:
        """已加载的模板 ID 列表。"""
        return list(self._templates.keys())

    def _load_template(self, path: Path) -> None:
        """从 YAML 文件加载单个模板。"""
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not data or "template_id" not in data:
            return

        dimensions = [
            JudgeDimension(
                dim_id=d["dim_id"],
                name=d["name"],
                description=d.get("description", ""),
                weight=d.get("weight", 1.0),
                score_range=tuple(d.get("score_range", [0.0, 10.0])),
            )
            for d in data.get("dimensions", [])
        ]

        template = JudgeTemplate(
            template_id=data["template_id"],
            name=data.get("name", data["template_id"]),
            dimensions=dimensions,
            system_prompt=data.get("system_prompt", ""),
            user_prompt_template=data.get("user_prompt_template", ""),
            output_schema=data.get("output_schema", {}),
            temperature=data.get("temperature", 0.0),
            seed=data.get("seed", 42),
            num_samples=data.get("num_samples", 3),
        )
        self._templates[template.template_id] = template
