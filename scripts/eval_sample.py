"""验收评估脚本 — 对指定样本目录执行完整评估。

使用方法:
    # 无 LLM（降级模式，快速验证）
    uv run python scripts/eval_sample.py

    # 指定样本目录
    uv run python scripts/eval_sample.py --sample-dir docs/reference/大单元学习总导

    # 含 LLM Judge（需先配置 .env 和 llm_config.yaml）
    uv run python scripts/eval_sample.py --llm-config llm_config.yaml
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# 项目根目录
ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    parser = argparse.ArgumentParser(description="评估课件样本")
    parser.add_argument(
        "--sample-dir",
        default=str(ROOT / "docs" / "reference" / "大单元学习总导"),
        help="样本目录路径",
    )
    parser.add_argument(
        "--rule-set",
        default=str(ROOT / "assets" / "rules" / "default_rule_set.yaml"),
        help="规则集 YAML 文件路径",
    )
    parser.add_argument(
        "--llm-config",
        default=None,
        help="LLM 配置文件路径（可选，不传则 LLM 评估器降级）",
    )
    parser.add_argument(
        "--output-dir",
        default=str(ROOT / "workspace"),
        help="输出目录",
    )
    args = parser.parse_args()

    # ─── 1. 打包 ───
    from agent_eval.execution.models import Task
    from agent_eval.storage.builder import PackageBuilder

    sample_dir = Path(args.sample_dir)
    if not sample_dir.exists():
        print(f"❌ 样本目录不存在: {sample_dir}")
        sys.exit(1)

    task = Task(
        id=sample_dir.name,
        input={"subject": "综合", "topic": sample_dir.name},
        input_mode="directory",
        constraints={"min_documents": 1, "max_documents": 30, "format": ["html"]},
        file_patterns=["*.html"],
    )

    pkg_dir = ROOT / "workspace" / "packages" / task.id
    pkg_dir.mkdir(parents=True, exist_ok=True)

    print(f"📦 打包样本: {sample_dir}")
    print(f"   → {pkg_dir}")

    PackageBuilder().build_directory(
        task=task,
        source_dir=sample_dir,
        package_dir=pkg_dir,
    )

    # ─── 2. 评估 ───
    from agent_eval.orchestrator import eval_packages

    print(f"\n🔍 开始评估...")
    if args.llm_config:
        print(f"   LLM Config: {args.llm_config}")
    else:
        print(f"   LLM: 未配置，LLM 评估器将降级为 Rule-based")

    result = eval_packages(
        package_dir=str(ROOT / "workspace" / "packages"),
        rule_set_path=args.rule_set,
        llm_config_path=args.llm_config,
        output_dir=args.output_dir,
        project=task.id,
    )

    # ─── 3. 输出结果 ───
    print("\n" + "=" * 50)
    print("  评估结果摘要")
    print("=" * 50)
    print(f"  运行 ID:    {result.run_id}")
    print(f"  总样本数:   {result.report.total_samples}")
    print(f"  DR (交付率): {result.report.dr:.2%}")
    print(f"  CPR (约束通过率): {result.report.cpr:.2%}")
    print(f"  Avg Reward:  {result.report.avg_reward:.2f}")
    print(f"  CondR (条件Reward): {result.report.cond_r:.2f}")
    print(f"  平均耗时:    {result.report.avg_time_ms:.0f}ms")

    if result.report.failure_breakdown:
        print(f"\n  ❌ 失败项:")
        for cid, count in result.report.failure_breakdown.items():
            print(f"     - {cid}: {count} 次")
    else:
        print(f"\n  ✅ 所有约束通过")

    print(f"\n  📁 结果目录: {result.run_workspace.root}")
    print(f"  📄 Markdown 报告: {result.run_workspace.reports_dir / 'summary.md'}")
    print(f"  📊 JSON 报告: {result.run_workspace.reports_dir / 'summary.json'}")

    # 打印 Markdown 报告内容
    summary_md = result.run_workspace.reports_dir / "summary.md"
    if summary_md.exists():
        print(f"\n{'─' * 50}")
        print(summary_md.read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
