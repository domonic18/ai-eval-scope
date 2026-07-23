"""Orchestrator — eval-only 模式编排。

将 ExecutionPackage 加载 → PipelineEngine 评估 → ReportGenerator 报告 串联为完整流程。
支持缓存持久化和 workspace index 更新。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import structlog
from dotenv import load_dotenv

# 在配置解析前加载 .env 中的环境变量
load_dotenv()

# 确保所有评估器注册到 registry（触发 @registry.register 装饰器）
import agent_eval.evaluation.evaluators  # noqa: F401
from agent_eval.config import SCORE_AGGREGATION_WEIGHTS
from agent_eval.core.exceptions import OrchestratorError
from agent_eval.evaluation.engine import PipelineEngine, build_default_pipeline, build_pipeline
from agent_eval.evaluation.models import (
    MetricsReport,
    SampleResult,
)
from agent_eval.evaluation.registry import registry
from agent_eval.evaluation.summary import SummaryGenerator
from agent_eval.reporting.report_generator import ReportGenerator
from agent_eval.storage.package import (
    EvalResultManifest,
    EvaluationResult,
    ExecutionPackage,
    ScoreSummary,
    find_orphan_files,
    generate_result_id,
    generate_run_id,
)
from agent_eval.storage.workspace import RunWorkspace, Workspace

logger = structlog.get_logger("orchestrator")


@dataclass
class EvalResult:
    """一次 eval 的完整结果。"""

    report: MetricsReport
    results: dict[str, EvaluationResult] = field(default_factory=dict)
    run_id: str = ""
    run_workspace: RunWorkspace | None = None
    samples: list[SampleResult] = field(default_factory=list)
    # 运行溯源：规则集版本，透传至 sink → run event → 平台
    rule_set_version: str = ""
    # S2-E：实际使用的规则集与场景配置，供 sink→run event→快照记录真实版本与指标定义
    rule_set: Any = None
    scenario_config: Any = None
    # 评估摘要报告（LLM 生成的人话总结，LLM 不可用时为 None）
    summary_report: dict[str, Any] | None = None


class Orchestrator:
    """编排调度器 — eval-only 模式。

    使用示例::

        orch = Orchestrator(engine, report_gen, workspace)
        result = orch.eval_only(package_dir, rule_set)
        print(result.report.dr)
    """

    def __init__(
        self,
        pipeline_engine: PipelineEngine | None = None,
        report_generator: ReportGenerator | None = None,
        workspace: Workspace | None = None,
    ) -> None:
        self.pipeline_engine = pipeline_engine or build_default_pipeline(registry)
        self.report_generator = report_generator or ReportGenerator()
        self.workspace = workspace or Workspace()

    def eval_only(
        self,
        package_dir: Path,
        rule_set: Any | None = None,
        *,
        judge_orchestrator: Any | None = None,
        run_workspace: RunWorkspace | None = None,
        llm_provider: str | None = None,
        project: str | None = None,
        with_vision: bool = False,
        screenshot_renderer: Any | None = None,
        vision_soft_weights: dict[str, float] | None = None,
        llm_signature: str = "",
        no_cache: bool = False,
    ) -> EvalResult:
        """eval-only 模式：加载 packages → 评估 → 报告。

        Args:
            package_dir: ExecutionPackage 目录路径（单个包或包含多个包的目录）。
            rule_set: 规则集（RuleSet 实例）。
            judge_orchestrator: LLM Judge 编排器（可选，无则评估器降级）。
            run_workspace: 运行工作空间（可选，自动创建）。
            llm_provider: LLM Provider 名称覆盖（可选）。
            project: 项目 ID（可选，用于 workspace index）。
            with_vision: 是否启用视觉评估器 vision.quality（默认 False）。
                视觉为 opt-in：需同时提供 screenshot_renderer 与支持视觉的 Provider。
            screenshot_renderer: ScreenshotRenderer 实例（with_vision=True 时必需，
                否则视觉评估器降级为默认通过）。
            vision_soft_weights: 启用视觉时的软约束权重映射（须含 vision.quality），
                默认 {teaching_logic:0.4, content_diversity:0.3, vision.quality:0.3}。

        Returns:
            EvalResult 实例。
        """
        # 管线由规则集构建（单一事实源）；视觉评估器是否纳入取决于规则集。
        # 传了 rule_set → 据其重建管线；未传（None）→ 复用 __init__ 的默认管线（已含全部评估器）。
        # with_vision=True 时显式覆盖软约束权重（含 vision.quality）以保持归一化正确。
        if rule_set is not None:
            self.pipeline_engine = build_pipeline(registry, rule_set)
        if with_vision:
            self.pipeline_engine.aggregator.soft_weights = vision_soft_weights or dict(
                SCORE_AGGREGATION_WEIGHTS.vision_soft_weights
            )
        package_dir = Path(package_dir)
        if not package_dir.exists():
            raise OrchestratorError(f"执行包目录不存在: {package_dir}")

        # 1. 创建或使用已有 RunWorkspace
        run_id = generate_run_id()
        if run_workspace is None:
            self.workspace.ensure_dirs()
            run_workspace = self.workspace.create_run(run_id)
        else:
            run_id = run_workspace.run_id

        run_workspace.write_run_manifest(
            {
                "mode": "eval_only",
                "package_dir": str(package_dir),
                "project": project,
            }
        )

        logger.info("开始 eval-only 评估", run_id=run_id, package_dir=str(package_dir))

        # 2. 为本次评测运行创建 Langfuse Trace
        # 同一运行内的所有 LLM/视觉 LLM 调用都归到这个 trace 下；
        # 不同运行使用不同 trace_id，实现任务级隔离。
        trace_id: str | None = None
        try:
            from agent_eval.llm.tracing import create_trace

            trace_info = create_trace(
                name=f"eval:{run_id}",
                metadata={
                    "run_id": run_id,
                    "mode": "eval_only",
                    "package_dir": str(package_dir),
                    "project": project,
                    "with_vision": with_vision,
                },
            )
            if trace_info is not None:
                trace_id = trace_info[1]["trace_id"]
        except Exception:
            logger.warning("创建 Langfuse trace 失败，将继续无追踪运行", exc_info=True)

        # 3. 加载 ExecutionPackage 列表
        packages = self._load_packages(package_dir)
        if not packages:
            raise OrchestratorError(f"未找到有效的 ExecutionPackage: {package_dir}")

        logger.info("加载执行包", count=len(packages))

        # 3.1 孤儿文件检测（兜底：pack 已为覆盖语义，此处防御 package 被外部篡改/旧版本残留，
        #     避免 silent corruption —— 评估了不属于本任务的内容）
        for pkg in packages:
            if pkg.output_dir and pkg.directory_manifest is not None:
                orphans = find_orphan_files(pkg.output_dir, pkg.directory_manifest)
                if orphans:
                    rel_paths = sorted(str(p.relative_to(pkg.output_dir)) for p in orphans)
                    logger.warning(
                        "检测到孤儿文件（manifest 未登记，可能污染评估结果）",
                        package_id=pkg.manifest.package_id,
                        count=len(orphans),
                        files=rel_paths,
                    )

        # 4. 加载缓存
        self._load_cache(self.workspace, self.pipeline_engine)

        # 6. 构建 extra_context
        rule_set_version = ""
        if rule_set is not None and hasattr(rule_set, "version"):
            rule_set_version = rule_set.version

        extra_context: dict[str, Any] = {}
        if judge_orchestrator is not None:
            extra_context["judge_orchestrator"] = judge_orchestrator
        if llm_provider is not None:
            extra_context["llm_provider"] = llm_provider
        if screenshot_renderer is not None:
            extra_context["screenshot_renderer"] = screenshot_renderer
        if trace_id is not None:
            extra_context["trace_id"] = trace_id
        # LLM 配置指纹（纳入 cache_key，LLM 配置/可用性变更时缓存自动失效）
        extra_context["llm_signature"] = llm_signature
        if no_cache:
            extra_context["no_cache"] = True

        # 为每个包设置 evidence_dir
        # 在 evaluate_batch 中通过 extra_context 统一注入，
        # 但每个包的 evidence_dir 不同，需要在循环中单独处理
        # 使用 per-sample context override

        # 7. 逐样本评估
        sample_results: list[SampleResult] = []
        result_map: dict[str, EvaluationResult] = {}

        for i, pkg in enumerate(packages):
            # 构建单个样本的上下文
            context = self.pipeline_engine._build_context(pkg, rule_set, index=i)
            context.update(extra_context)

            # 设置 evidence_dir
            task_id = context.get("sample_id", f"task_{i:03d}")
            result_dir = run_workspace.get_result_dir(task_id)
            evidence_dir = result_dir / "evidence"
            context["evidence_dir"] = evidence_dir

            sample_result = self.pipeline_engine.evaluate_sample(pkg, context)
            sample_results.append(sample_result)

            # 8. 转为 EvaluationResult 并保存
            eval_result = self._sample_to_evaluation_result(
                sample_result,
                pkg,
                run_id,
                rule_set_version,
            )
            eval_result.save(result_dir)
            result_map[task_id] = eval_result

            logger.info(
                "样本评估完成",
                sample_id=task_id,
                status=sample_result.status.value,
                reward=sample_result.reward,
            )

        # 9. 计算聚合指标
        metrics_report = self.pipeline_engine.metrics_calculator.compute(
            sample_results,
            run_id=run_id,
        )

        # 10. 生成聚合报告
        summary_md, summary_json = self.report_generator.generate_summary_report(
            metrics_report,
        )
        (run_workspace.reports_dir / "summary.md").write_text(
            summary_md,
            encoding="utf-8",
        )
        # 注入运行溯源（供 upload 子命令从 summary.json 重建 run event）
        summary_json["rule_set_version"] = rule_set_version
        (run_workspace.reports_dir / "summary.json").write_text(
            json.dumps(summary_json, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        # 11. 生成评估摘要报告（LLM 人话总结，LLM 不可用时跳过）
        summary_report: dict[str, Any] | None = None
        try:
            from agent_eval.config.loader import ConfigLoader
            from agent_eval.config.paths import paths

            llm_cfg_path = paths.configs_dir / "llm_config.yaml"
            if llm_cfg_path.exists():
                llm_config = ConfigLoader.load_llm_config(llm_cfg_path)
                from agent_eval.llm.pool import ProviderPool

                pool = ProviderPool(llm_config)
                scenario_name = project if project else ""
                # 指标定义（含 summary）
                metric_defs: list[dict[str, Any]] = []
                scenario_cfg = getattr(self.pipeline_engine, "scenario_config", None)
                if scenario_cfg:
                    metric_defs = [m.model_dump() for m in scenario_cfg.metric_definitions]
                # 仅传内容质量指标，且键须与 metric_definitions 对齐。
                # avg_time_ms 是「评测耗时」过程元数据，不属于被评估对象的质量维度，
                # 不进入摘要输入（否则 LLM 会对评测时间做评价）。
                metrics_dict = {
                    "courseware:document_rate": metrics_report.dr,
                    "courseware:constraint_pass_rate": metrics_report.cpr,
                    "courseware:reward": metrics_report.avg_reward,
                    "courseware:soft": metrics_report.avg_soft,
                    "courseware:pref": metrics_report.avg_pref,
                    "courseware:conditional_reward": metrics_report.cond_r,
                }
                summary_report = SummaryGenerator(pool).generate(
                    metrics=metrics_dict,
                    sample_results=sample_results,
                    metric_definitions=metric_defs,
                    scenario=scenario_name,
                )
                if summary_report:
                    logger.info("summary_generator.ok", headline=summary_report.get("headline", ""))
                    # 回写 summary.json（供 upload 子命令重建 run event 时携带）
                    summary_json["summary_report"] = summary_report
                    (run_workspace.reports_dir / "summary.json").write_text(
                        json.dumps(summary_json, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                else:
                    logger.info("summary_generator.skip", reason="llm_unavailable_or_parse_failed")
        except Exception as e:
            logger.warning("summary_generator.error", error=str(e))

        # 12. 保存缓存
        self._save_cache(self.workspace, self.pipeline_engine)

        # 12. 更新 workspace index
        self._update_workspace_index(
            self.workspace,
            run_workspace,
            metrics_report,
            project,
        )

        logger.info(
            "eval-only 评估完成",
            run_id=run_id,
            total_samples=metrics_report.total_samples,
            dr=metrics_report.dr,
            cpr=metrics_report.cpr,
            avg_reward=metrics_report.avg_reward,
        )

        scenario_cfg = getattr(self.pipeline_engine, "scenario_config", None)
        return EvalResult(
            report=metrics_report,
            results=result_map,
            run_id=run_id,
            run_workspace=run_workspace,
            samples=sample_results,
            rule_set_version=rule_set_version,
            rule_set=rule_set,
            scenario_config=scenario_cfg,
            summary_report=summary_report,
        )

    def _load_packages(self, package_dir: Path) -> list[ExecutionPackage]:
        """扫描目录，加载所有 ExecutionPackage。

        支持两种模式:
        - package_dir 本身就是单个包目录（含 manifest.json）
        - package_dir 包含多个子目录，每个子目录是一个包
        """
        packages: list[ExecutionPackage] = []

        if not package_dir.exists():
            raise OrchestratorError(f"执行包目录不存在: {package_dir}")

        # 检查是否本身就是单个包
        if (package_dir / "manifest.json").exists():
            try:
                pkg = ExecutionPackage.load(package_dir)
                packages.append(pkg)
                return packages
            except Exception as e:
                raise OrchestratorError(
                    f"加载执行包失败: {package_dir}: {e}",
                ) from e

        # 扫描子目录
        subdirs = sorted(d for d in package_dir.iterdir() if d.is_dir())
        if not subdirs:
            raise OrchestratorError(
                f"目录中未找到执行包（无子目录且无 manifest.json）: {package_dir}",
            )

        for subdir in subdirs:
            if (subdir / "manifest.json").exists():
                try:
                    pkg = ExecutionPackage.load(subdir)
                    packages.append(pkg)
                except Exception as e:
                    logger.warning("跳过无效包", path=str(subdir), error=str(e))

        return packages

    def _sample_to_evaluation_result(
        self,
        sample_result: SampleResult,
        package: ExecutionPackage,
        run_id: str,
        rule_set_version: str,
    ) -> EvaluationResult:
        """将 SampleResult 转为 EvaluationResult 输出格式。"""
        task_id = sample_result.sample_id
        package_id = package.manifest.package_id
        result_id = generate_result_id(run_id, task_id)

        # ConstraintResult → rule_results 列表
        rule_results = self.report_generator.sample_to_rule_results(sample_result)

        # 评分
        scores = ScoreSummary(
            s_format=sample_result.s_format,
            s_common=sample_result.s_common,
            s_soft=sample_result.s_soft,
            s_pref=sample_result.s_pref,
            reward=sample_result.reward,
        )

        # 报告
        task_md, task_json = self.report_generator.generate_task_report(sample_result)

        return EvaluationResult(
            manifest=EvalResultManifest(
                result_id=result_id,
                package_id=package_id,
                rule_set_version=rule_set_version,
                evaluated_at=datetime.now(UTC).isoformat(),
            ),
            rule_results=rule_results,
            scores=scores,
            report_markdown=task_md,
            report_json=task_json,
        )

    def _load_cache(
        self,
        workspace: Workspace,
        engine: PipelineEngine,
    ) -> None:
        """从磁盘加载缓存到 PipelineEngine。"""
        cache_file = workspace.cache_dir / "evaluation_cache.json"
        if not cache_file.exists():
            return

        try:
            data = json.loads(cache_file.read_text(encoding="utf-8"))
            count = 0
            for key, val in data.items():
                try:
                    engine._cache[key] = SampleResult.from_dict(val)
                    count += 1
                except Exception:
                    pass
            if count:
                logger.info("加载评估缓存", entries=count)
        except Exception as e:
            logger.warning("缓存加载失败，跳过", error=str(e))

    def _save_cache(
        self,
        workspace: Workspace,
        engine: PipelineEngine,
    ) -> None:
        """将 PipelineEngine 缓存持久化到磁盘。"""
        workspace.ensure_dirs()
        cache_file = workspace.cache_dir / "evaluation_cache.json"
        try:
            data = {k: v.to_dict() for k, v in engine._cache.items()}
            cache_file.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            logger.info("保存评估缓存", entries=len(data))
        except Exception as e:
            logger.warning("缓存保存失败", error=str(e))

    def _update_workspace_index(
        self,
        workspace: Workspace,
        run_ws: RunWorkspace,
        metrics_report: MetricsReport,
        project: str | None,
    ) -> None:
        """评估完成后更新 workspace 索引，供 Web Portal 读取。"""
        workspace.ensure_dirs()
        index_file = workspace.index_dir / "runs_index.json"

        try:
            if index_file.exists():
                runs_index = json.loads(index_file.read_text(encoding="utf-8"))
            else:
                runs_index = {"runs": []}

            # 确保 runs 是列表
            if not isinstance(runs_index.get("runs"), list):
                runs_index["runs"] = []

            run_entry: dict[str, Any] = {
                "run_id": run_ws.run_id,
                "mode": "eval_only",
                "total_samples": metrics_report.total_samples,
                "metrics": {
                    "DR": metrics_report.dr,
                    "CPR": metrics_report.cpr,
                    "avg_reward": metrics_report.avg_reward,
                    "condR": metrics_report.cond_r,
                    "avg_time_ms": metrics_report.avg_time_ms,
                },
                "failure_breakdown": metrics_report.failure_breakdown,
                "created_at": datetime.now(UTC).isoformat(),
            }
            if project:
                run_entry["project"] = project

            runs_index["runs"].append(run_entry)
            index_file.write_text(
                json.dumps(runs_index, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            logger.info("更新 workspace 索引", run_id=run_ws.run_id)
        except Exception as e:
            logger.warning("workspace 索引更新失败", error=str(e))


def _init_judge_orchestrator(
    llm_config: Any | None = None,
    llm_provider: str | None = None,
) -> Any | None:
    """初始化 JudgeOrchestrator。

    Args:
        llm_config: LLMConfig 实例（可选）。
        llm_provider: Provider 名称覆盖（可选）。

    Returns:
        JudgeOrchestrator 实例，或 None（无 LLM 配置时）。
    """
    if llm_config is None:
        return None

    try:
        from agent_eval.config import LLMConfig
        from agent_eval.llm.judge.orchestrator import JudgeOrchestrator
        from agent_eval.llm.judge.stability import StabilityController
        from agent_eval.llm.judge.structured_output import StructuredOutputParser
        from agent_eval.llm.judge.template_manager import TemplateManager
        from agent_eval.llm.pool import ProviderPool

        if not isinstance(llm_config, LLMConfig):
            return None

        pool = ProviderPool(llm_config)
        from agent_eval.config.paths import paths

        templates = TemplateManager(paths.prompts_dir)
        templates.load_all()
        stability = StabilityController()
        parser = StructuredOutputParser()

        return JudgeOrchestrator(
            pool=pool,
            template_manager=templates,
            stability=stability,
            parser=parser,
        )
    except Exception as e:
        logger.warning("JudgeOrchestrator 初始化失败，LLM 评估器将降级", error=str(e))
        return None


def eval_packages(
    package_dir: str | Path,
    rule_set_path: str | Path | None = None,
    *,
    llm_config_path: str | Path | None = None,
    output_dir: str | Path | None = None,
    llm_provider: str | None = None,
    project: str | None = None,
) -> EvalResult:
    """SDK eval 接口 — Python 可直接调用。

    使用示例::

        result = eval_packages(
            "./workspace/runs/xxx/packages",
            rule_set_path="./rule_set.yaml",
        )
        print(result.report.dr)

    Args:
        package_dir: ExecutionPackage 目录路径。
        rule_set_path: 规则集 YAML 文件路径（可选）。
        llm_config_path: LLM 配置 YAML 文件路径（可选）。
        output_dir: 输出目录（可选，默认 ./workspace）。
        llm_provider: LLM Provider 名称覆盖（可选）。
        project: 项目 ID（可选）。

    Returns:
        EvalResult 实例。

    能力（LLM/视觉）由规则集声明派生：含 vision.* 评估器即自动
    启用视觉管线 + PlaywrightScreenshotRenderer（需安装 vision extra + Chromium）。
    """
    from agent_eval.config.loader import ConfigLoader

    # 加载 RuleSet（可选）
    rule_set = None
    if rule_set_path:
        rule_set = ConfigLoader.load_rule_set(rule_set_path)

    # 加载 LLM 配置（可选）
    llm_config = None
    if llm_config_path:
        llm_config = ConfigLoader.load_llm_config(llm_config_path)

    # 初始化 JudgeOrchestrator（可选）
    judge_orch = _init_judge_orchestrator(llm_config, llm_provider)

    # 创建 Workspace
    workspace = Workspace(output_dir) if output_dir else Workspace()

    # 创建 Orchestrator 并执行
    orch = Orchestrator(workspace=workspace)

    renderer = None
    try:
        # 能力派生：视觉是否启用由规则集派生（含 vision.* 评估器即启用）。
        # 单一事实源 —— 规则集声明 vision.* 评估器即自动启用，无需 CLI/HTTP flag。
        from agent_eval.core.types import Capability
        from agent_eval.evaluation.capability import CapabilityResolver

        required = CapabilityResolver(registry).resolve(rule_set)
        want_vision = Capability.VISION in required.capabilities
        if want_vision:
            from agent_eval.evaluation.vision import PlaywrightScreenshotRenderer

            renderer = PlaywrightScreenshotRenderer()

        result = orch.eval_only(
            Path(package_dir),
            rule_set,
            judge_orchestrator=judge_orch,
            llm_provider=llm_provider,
            project=project,
            with_vision=want_vision,
            screenshot_renderer=renderer,
        )
    finally:
        if renderer is not None:
            renderer.close()

    # 刷新 Langfuse trace 数据
    from agent_eval.llm.tracing import flush_traces

    flush_traces()

    return result
