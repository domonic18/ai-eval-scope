"""FilePromptStore — 从场景包 prompts/ 目录加载（Phase 1，等价替代 TemplateManager 读路径）。

复用 TemplateManager 的 _load_template（YAML 解析），按 template_id 索引；
scenario_id 可选过滤（兼容旧式无场景 YAML）。version/label 对文件无意义（文件未版本化），忽略。
"""

from __future__ import annotations

from pathlib import Path

from agent_eval.llm.judge.prompt_store import PromptStore, PromptTemplateSummary
from agent_eval.llm.judge.template_manager import JudgeTemplate, TemplateManager


class FilePromptStore(PromptStore):
    """从本地场景包 prompts/ 目录加载 Prompt 模板。"""

    def __init__(self, template_dir: Path | str) -> None:
        self._tm = TemplateManager(template_dir)

    def load_all(self) -> None:
        """加载目录下所有 YAML 模板（委托 TemplateManager）。"""
        self._tm.load_all()

    def get(
        self,
        scenario_id: str | None,
        template_id: str,
        version: str | None = None,
        label: str | None = None,
    ) -> JudgeTemplate:
        template = self._tm.get(template_id)  # 不存在抛 LLMError
        # scenario_id 过滤：给定 scenario_id 且模板声明了 scenario_id 且不等 → 报错
        if scenario_id and template.scenario_id and template.scenario_id != scenario_id:
            from agent_eval.core.exceptions import LLMError

            raise LLMError(
                f"模板 {template_id} 不属场景 {scenario_id}（实际: {template.scenario_id}）",
                details={"template_id": template_id, "scenario_id": scenario_id},
            )
        # version/label 对 File 无意义（文件未版本化），忽略
        return template

    def list(self, scenario_id: str | None = None) -> list[PromptTemplateSummary]:
        result: list[PromptTemplateSummary] = []
        for tid in self._tm.template_ids:
            t = self._tm.get(tid)
            if scenario_id and t.scenario_id and t.scenario_id != scenario_id:
                continue
            result.append(
                PromptTemplateSummary(
                    template_id=t.template_id,
                    name=t.name,
                    namespace=t.namespace,
                    scenario_id=t.scenario_id,
                    version=t.version,
                    labels=t.labels,
                    content_hash=t.content_hash,
                )
            )
        return result

    @property
    def template_ids(self) -> list[str]:
        """已加载的模板 ID 列表（兼容旧调用 orchestrator.templates.get/直访点）。"""
        return self._tm.template_ids
