"""agent-eval upload — 历史运行评估结果回填可观测平台（Sprint 7e）。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import typer

from agent_eval.cli._common import rprint


def upload(
    run: str = typer.Option(..., "--run", help="要回填的运行 ID（workspace/runs/{run}）"),
    workspace: str = typer.Option("./workspace", "--workspace", help="Workspace 目录"),
    project: str | None = typer.Option(
        None, "--project", help="目标项目（覆盖 AGENT_EVAL_PROJECT）"
    ),
) -> None:
    """把历史运行的评估结果回填到可观测平台（Sprint 7e）。

    从 workspace/runs/{run}/ 的 summary.json + 各 task 的 report.json 重建事件并推送。
    需配置 AGENT_EVAL_HOST / AGENT_EVAL_API_KEY。
    """
    upload_run(run=run, workspace=workspace, project=project)


def upload_run(
    run: str,
    workspace: str = "./workspace",
    project: str | None = None,
) -> None:
    """回填动作（纯函数；重建 run/sample/constraint/artifact 事件并推送）。"""
    import json as _json

    from agent_eval.evaluation.models import SampleResult
    from agent_eval.observability import ResultSink, load_config
    from agent_eval.observability.events import (
        build_artifact_event,
        build_constraint_event,
        build_run_event,
        build_sample_event,
    )
    from agent_eval.observability.sink import SinkReport

    run_dir = Path(workspace).resolve() / "runs" / run
    if not run_dir.exists():
        rprint(f"[red]运行目录不存在: {run_dir}[/red]")
        raise typer.Exit(code=1)

    summary_path = run_dir / "reports" / "summary.json"
    if not summary_path.exists():
        rprint(f"[red]缺少 summary.json: {summary_path}[/red]")
        raise typer.Exit(code=1)
    summary = _json.loads(summary_path.read_text(encoding="utf-8"))

    # 回填沿用真实运行模式：run 清单 mode=run → agent；mode=pipeline → pipeline
    manifest_path = run_dir / "run_manifest.json"
    run_mode = "eval_only"
    if manifest_path.exists():
        try:
            _m = _json.loads(manifest_path.read_text(encoding="utf-8")).get("mode")
            if _m == "run":
                run_mode = "agent"
            elif _m == "pipeline":
                run_mode = "pipeline"
        except (OSError, ValueError):
            pass

    env_override: dict[str, str] = {}
    if project:
        env_override["AGENT_EVAL_PROJECT"] = project
    # upload 子命令默认强制开启上传
    cfg = load_config(upload_override=True)
    if not cfg.has_credentials():
        rprint("[red]未配置凭据：请设置 AGENT_EVAL_HOST / AGENT_EVAL_API_KEY[/red]")
        raise typer.Exit(code=1)

    metrics = summary.get("metrics", {})
    # 用 build_run_event 重建 run 事件（附带场景化指标键 + scenario_id + 运行配置快照）
    from agent_eval.evaluation.models import MetricsReport

    # summary["metrics"] 已是场景化指标 dict（key=metric_id）；avg_time_ms 为顶层过程元数据
    report = MetricsReport(
        run_id=summary.get("run_id", run),
        total_samples=summary.get("total_samples", 0),
        metrics={
            k: float(v)
            for k, v in metrics.items()
            if k != "avg_time_ms" and isinstance(v, int | float)
        },
        avg_time_ms=summary.get("avg_time_ms", metrics.get("avg_time_ms", 0.0)),
    )
    # 从 summary 重建 ScenarioConfig，使回填 run 的 scenario_id/指标定义与原运行一致
    # （S2-13：不再回退 courseware）。scenario_id 由指标 id 前缀推导（如 code:delivery_rate → code）。
    from agent_eval.evaluation.scenario.models import (
        AggregationPolicy,
        MetricDefinition,
        ScenarioConfig,
    )

    mdefs_raw = summary.get("metric_definitions") or []
    backfill_sid = str(mdefs_raw[0]["id"]).split(":", 1)[0] if mdefs_raw else "courseware"
    scenario_config = ScenarioConfig(
        scenario_id=backfill_sid,
        aggregation_policy=AggregationPolicy(
            id=f"{backfill_sid}-backfill", scenario_id=backfill_sid, stage_weights=[]
        ),
        metric_definitions=[MetricDefinition.model_validate(m) for m in mdefs_raw],
    )
    events: list[dict[str, Any]] = [
        build_run_event(
            report,
            mode=run_mode,
            rule_set_version=summary.get("rule_set_version"),
            summary_report=summary.get("summary_report"),
            scenario_config=scenario_config,
        ),
    ]

    results_dir = run_dir / "results"
    sample_count = 0
    if results_dir.exists():
        for task_dir in sorted(p for p in results_dir.iterdir() if p.is_dir()):
            report_path = task_dir / "report.json"
            if not report_path.exists():
                continue
            try:
                sample = SampleResult.from_dict(
                    _json.loads(report_path.read_text(encoding="utf-8"))
                )
            except Exception as exc:  # noqa: BLE001
                rprint(f"[yellow]跳过 {task_dir.name}: 解析失败 {exc}[/yellow]")
                continue
            events.append(build_sample_event(sample, external_run_id=summary.get("run_id", run)))
            for stage in sample.stage_results.values():
                for c in stage.constraint_results:
                    events.append(
                        build_constraint_event(
                            c,
                            external_run_id=summary.get("run_id", run),
                            external_sample_id=sample.sample_id,
                        )
                    )
            sample_count += 1

    # ── artifacts: 扫描 evidence/ 目录上传截图 + judge 记录；扫描 package 上传原始文件 ──
    run_id_str = summary.get("run_id", run)
    sink = ResultSink(cfg)
    art_report = SinkReport(enabled=True)
    artifact_count = 0

    # 从 run_manifest 获取 package_dir（原始产出物所在）
    manifest_path = run_dir / "run_manifest.json"
    package_dir_str = ""
    if manifest_path.exists():
        package_dir_str = _json.loads(manifest_path.read_text(encoding="utf-8")).get(
            "package_dir", ""
        )

    if results_dir.exists():
        for task_dir in sorted(p for p in results_dir.iterdir() if p.is_dir()):
            report_path = task_dir / "report.json"
            if not report_path.exists():
                continue
            try:
                sample = SampleResult.from_dict(
                    _json.loads(report_path.read_text(encoding="utf-8"))
                )
            except Exception:
                continue

            evidence_dir = task_dir / "evidence"
            if evidence_dir.exists():
                # 截图（.png）
                for shot in sorted(evidence_dir.glob("*.png")):
                    ok_obj = sink._upload_artifact(
                        shot,
                        external_run_id=run_id_str,
                        external_sample_id=sample.sample_id,
                        kind="screenshot",
                        content_type="image/png",
                        original_name=shot.name,
                        report=art_report,
                    )
                    if ok_obj:
                        events.append(
                            build_artifact_event(
                                external_run_id=run_id_str,
                                external_sample_id=sample.sample_id,
                                kind="screenshot",
                                object_key=ok_obj,
                                content_type="image/png",
                                size_bytes=shot.stat().st_size,
                                original_name=shot.name,
                            )
                        )
                        artifact_count += 1
                # judge 记录（judge_*.json）
                for jf in sorted(evidence_dir.glob("judge_*.json")):
                    ok_obj = sink._upload_artifact(
                        jf,
                        external_run_id=run_id_str,
                        external_sample_id=sample.sample_id,
                        kind="judge_record",
                        content_type="application/json",
                        original_name=jf.name,
                        report=art_report,
                    )
                    if ok_obj:
                        events.append(
                            build_artifact_event(
                                external_run_id=run_id_str,
                                external_sample_id=sample.sample_id,
                                kind="judge_record",
                                object_key=ok_obj,
                                content_type="application/json",
                                size_bytes=jf.stat().st_size,
                                original_name=jf.name,
                            )
                        )
                        artifact_count += 1

    # 原始产出物：按样本归属上传（output/ 产物 + 执行包技术文件分类）——需样本列表
    if package_dir_str:
        pkg = Path(package_dir_str)
        if pkg.exists():
            # 从 results/ 重建样本引用（sample_id = task_id），供归属
            from types import SimpleNamespace

            sids = (
                [
                    d.name
                    for d in (run_dir / "results").iterdir()
                    if d.is_dir() and (d / "report.json").exists()
                ]
                if (run_dir / "results").is_dir()
                else []
            )
            if sids:
                src_events = sink._upload_package_artifacts(
                    pkg, run_id_str, [SimpleNamespace(sample_id=sid) for sid in sids], art_report
                )
                events.extend(src_events)
                artifact_count += len(src_events)

    rprint(
        f"[blue]回填:[/blue] 运行 {run}，样本 {sample_count}，"
        f"事件 {len(events)}（含 {artifact_count} 制品）"
    )
    sent, queued = sink.dispatch(events)
    rprint(f"[green]✓ 回填完成[/green] 已发送 {sent}、入队 {queued}")
