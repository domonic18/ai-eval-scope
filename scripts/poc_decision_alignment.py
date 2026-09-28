"""判定专线（decision）误触预筛对拍 PoC（一次性人工运行工具，不入测试/CI）。

工作流（判定专线误触预筛对拍校准）：
  smoke  — 连通性冒烟：单次 Noul 调用验证 key/网络/契约/resolved model（缺省命令）
  export — 规则引擎重放导出 error 级候选 JSONL（label 留空，人工标注：1=真错误 / 0=误触）
  run    — Noul 判定 vs 人工标签：agreement / Cohen's κ / 漏报率 / 延迟 / 成本

用法（evaluator/ 下）：uv run python ../scripts/poc_decision_alignment.py [smoke|export|run]
    export 加 --source <样本目录>；run 加 --candidates <jsonl> [--limit 20 先小样]
    模型/端点/阈值可参数化：--model / --api-url / --drop-below（换模型须重跑对拍）

密钥纪律：OPENROUTER_API_KEY 只从环境/仓库根 .env 读取，禁止出现在任何输出/日志/报告中。
通道绑定：结论仅对所配通道（缺省 OpenRouter POST /api/alpha/decisions）成立，切换须重跑对拍。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_API_URL = "https://openrouter.ai/api/alpha/decisions"
DEFAULT_MODEL = "typesafe/jev-1.13"  # 当前选型 pin（--model 可换同协议模型）；勿用漂移别名
RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})
DEFAULT_DROP_BELOW = 0.50  # 对拍校准定标（2026-09-24），勿回退 0.10
DEFAULT_SOURCE = REPO_ROOT / "samples" / "大单元学习总导"
DEFAULT_OUT = REPO_ROOT / "evaluator" / "workspace" / "poc" / "jev_candidates.jsonl"

# 与产品侧 fact_verdict 判定原则对齐（assets/packages/courseware/.../prompts/fact_verdict.yaml）
NOUL_QUESTION: dict[str, Any] = {
    "type": "noul",
    "instructions": (
        "你是课件事实核查员。state.text 为课件原文片段，state.claim 为规则引擎报出的"
        "疑似知识性错误描述。请判断该疑似错误是否真实成立。"
    ),
    "criteria": {
        "true": "成立：原文确实在陈述该事实，且其中的数值/事实关系确实错误。",
        "false": "不成立（误触）：所述内容在原文中并不存在、数值系跨段误抓、断章取义，或陈述本身正确。",
    },
}


class _TransientError(Exception):
    """瞬时错误（超时/连接中断/429/5xx），可重试一次；status 供 429 统计。"""

    def __init__(self, msg: str, status: int | None = None) -> None:
        super().__init__(msg)
        self.status = status


def _load_api_key() -> str:
    load_dotenv(REPO_ROOT / ".env")  # 已导出到环境时为 no-op
    key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not key:
        print("错误：未找到 OPENROUTER_API_KEY——写入仓库根 .env 或导出到环境变量", file=sys.stderr)
        raise SystemExit(1)
    return key


def _noul_call(
    client: httpx.Client,
    api_key: str,
    state: dict[str, str],
    model: str = DEFAULT_MODEL,
    api_url: str = DEFAULT_API_URL,
    counters: dict[str, int] | None = None,
) -> tuple[float, float, dict[str, Any]]:
    """单候选 Noul 判定 → (p_yes, latency_ms, raw)；瞬时错误重试 1 次（对齐 DecisionClient 设计）。"""
    body = {"model": model, "state": state, "questions": {"is_real_error": NOUL_QUESTION}}
    last: Exception | None = None
    for attempt in (1, 2):
        if attempt == 2 and counters is not None:  # GIL 下 dict 单键自增足够用于 PoC 统计
            counters["retries"] = counters.get("retries", 0) + 1
        start = time.perf_counter()
        try:
            resp = client.post(api_url, json=body, headers={"Authorization": f"Bearer {api_key}"})
            if resp.status_code in RETRYABLE_STATUS:
                raise _TransientError(f"HTTP {resp.status_code}", status=resp.status_code)
            if resp.status_code != 200:
                raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:300]}")
        except (httpx.TimeoutException, httpx.TransportError, _TransientError) as exc:
            if counters is not None and getattr(exc, "status", None) == 429:
                counters["http_429"] = counters.get("http_429", 0) + 1
            last = exc
            continue
        data = resp.json()
        latency_ms = (time.perf_counter() - start) * 1000
        try:
            p_yes = float(data["answers"]["is_real_error"]["noul"])
        except (KeyError, TypeError, ValueError) as exc:
            raise RuntimeError(f"响应缺 noul 字段（顶层键: {sorted(data)}）") from exc
        return p_yes, latency_ms, data
    raise RuntimeError(f"重试后仍失败: {last}")


def _cmd_smoke(args: argparse.Namespace) -> int:
    api_key = _load_api_key()
    with httpx.Client(timeout=httpx.Timeout(args.timeout)) as client:
        state = {
            # 真实成立 = 错误等式真实存在于原文：25×30 应为 750，原文却写 7500
            "text": "食堂每天消耗大米 25 千克，一个月按 30 天计算，共需要大米 7500 千克。",
            "claim": "算术错误: 25 × 30 = 7500（应为 750）",
        }
        p_yes, latency_ms, data = _noul_call(
            client, api_key, state, model=args.model, api_url=args.api_url
        )  # 期望 p ≥ 0.9
    print(
        f"resolved model : {data.get('model', '(响应未回显)')}\n"
        f"p(claim 成立)  : {p_yes:.4f}（构造为真实错误，期望 ≥ 0.9）｜latency: {latency_ms:.0f} ms\n"
        f"usage          : {data.get('usage', {})}"
    )
    if p_yes < 0.5:
        print("⚠️  p < 0.5：通道已通但语义方向可疑——检查 criteria 定义或通道行为")
        return 1
    print("✅ 冒烟通过")
    return 0


def _cmd_export(args: argparse.Namespace) -> int:
    sources = [Path(s).resolve() for s in (args.source or [str(DEFAULT_SOURCE)])]
    bad = [s for s in sources if not s.is_dir()]
    if bad:
        print(f"错误：源目录不存在: {bad}", file=sys.stderr)
        return 1
    from agent_eval.evaluation.evaluators import (
        commonsense_evaluators as cse,  # 惰性导入：smoke/run 不依赖项目包
    )

    out_path = DEFAULT_OUT
    # 多目录合并导出；key 加目录名前缀，防跨目录同名文件互相覆盖
    file_texts: dict[str, str] = {}
    for src in sources:
        for rel, text in cse._collect_file_texts(src).items():
            file_texts[f"{src.name}/{rel}"] = text
    if not file_texts:
        print(f"错误：{sources} 未收集到课件文本", file=sys.stderr)
        return 1
    # 生产默认参数：subjects=None → 全部学科；fact_rules=[] → _check_rules 空转跳过
    ev, fact_db = cse.InfoAccuracyEvaluator(), cse._load_fact_db(None)
    all_findings: list[dict[str, Any]] = []
    for findings, _checks in (
        ev._check_arithmetic(file_texts),
        ev._check_constants(file_texts, fact_db),
    ):
        all_findings.extend(findings)
    # 仅取 error 级——与 fact_verdict 复核人口同口径（misconceptions 恒 warning、从不升级）
    error_findings = [f for f in all_findings if f.get("severity") == "error"]
    records: dict[str, dict[str, Any]] = {}
    for f in error_findings:
        cid = hashlib.sha1(f"{f['file']}\n{f['message']}".encode()).hexdigest()[:12]
        if cid in records:  # 同文件同 message 重复出现，只标一次
            continue
        records[cid] = {
            "id": cid,
            "file": f["file"],
            "check_type": f["check_type"],
            "message": f["message"],
            "context": cse.InfoAccuracyEvaluator._extract_finding_context(f, file_texts),
            "label": None,  # 人工标注：1=真错误 / 0=误触
        }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    ordered = sorted(records.values(), key=lambda r: (r["file"], r["message"]))
    out_path.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in ordered), encoding="utf-8"
    )
    print(
        f"findings 总数 {len(all_findings)}｜error 级候选 {len(error_findings)}（fact_verdict 同口径）"
        f"｜去重导出 {len(records)} 条 → {out_path}\n"
        "下一步：人工标注 label 字段（1=真错误 / 0=误触），再运行 run 子命令"
    )
    return 0


def _judge_one(
    client: httpx.Client, api_key: str, rec: dict[str, Any], model: str, api_url: str
) -> tuple[str, float, float, float]:
    p, lat, data = _noul_call(
        client,
        api_key,
        {"text": rec["context"], "claim": rec["message"]},
        model=model,
        api_url=api_url,
    )
    return rec["id"], p, lat, float(data.get("usage", {}).get("cost") or 0.0)


def _cmd_run(args: argparse.Namespace) -> int:
    api_key = _load_api_key()
    path = Path(args.candidates or "").resolve()
    if not path.is_file():
        print(f"错误：候选文件不存在（检查 --candidates）: {path}", file=sys.stderr)
        return 1
    recs = [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    labeled = [r for r in recs if r.get("label") in (0, 1)]
    if not labeled:
        print("错误：无已标注候选（label 须为 1=真错误 / 0=误触）", file=sys.stderr)
        return 1
    if args.limit:
        labeled = labeled[: args.limit]
    counters: dict[str, int] = {}
    results: dict[str, tuple[float, float]] = {}  # id -> (p_yes, latency_ms)
    failed: list[str] = []
    cost_total, total = 0.0, len(labeled)
    with (
        httpx.Client(timeout=httpx.Timeout(args.timeout)) as client,
        ThreadPoolExecutor(max_workers=args.concurrency) as pool,
    ):
        futures = {
            pool.submit(_judge_one, client, api_key, r, args.model, args.api_url): r
            for r in labeled
        }
        for done, fut in enumerate(as_completed(futures), 1):
            rec = futures[fut]
            try:
                cid, p, lat, cost = fut.result()
            except RuntimeError as exc:
                failed.append(rec["id"])
                print(f"  [{done}/{total}] {rec['id']} 失败: {exc}")
                continue
            results[cid] = (p, lat)
            cost_total += cost
            if done % 25 == 0 or done == total:
                print(f"  进度 {done}/{total}（失败 {len(failed)}）")

    def _bucket(label: int, pid: str) -> str:
        """混淆矩阵分桶：predicted_real = p >= drop_below（对齐 v1 过滤语义）。"""
        if label == 1:
            return (
                "tp" if results[pid][0] >= args.drop_below else "fn"
            )  # 真错误：升级 / 剔除=漏报（红线）
        return (
            "fp" if results[pid][0] >= args.drop_below else "tn"
        )  # 误触：漏过滤（LLM 兜底）/ 正确剔除

    counts = Counter(_bucket(r["label"], r["id"]) for r in labeled if r["id"] in results)
    tp, fp, fn, tn = counts["tp"], counts["fp"], counts["fn"], counts["tn"]
    n, n_real = tp + tn + fp + fn, tp + fn
    agreement = (tp + tn) / n if n else 0.0
    pe = ((tp + fp) * n_real + (tn + fn) * (n - n_real)) / (n * n) if n else 0.0
    kappa = (agreement - pe) / (1 - pe) if pe < 1 else 0.0
    fn_rate = fn / n_real if n_real else 0.0
    lat_sorted = sorted(lat for _p, lat in results.values())
    p50 = lat_sorted[max(0, math.ceil(0.50 * len(lat_sorted)) - 1)] if lat_sorted else 0.0
    p95 = lat_sorted[max(0, math.ceil(0.95 * len(lat_sorted)) - 1)] if lat_sorted else 0.0
    report = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "api_url": args.api_url,  # 通道绑定声明
        "model": args.model,
        "drop_below": args.drop_below,
        "confusion": {"tp": tp, "fp": fp, "tn": tn, "fn": fn},
        "agreement": round(agreement, 4),
        "kappa": round(kappa, 4),
        "fn_rate_dropped_real_errors": round(fn_rate, 4),
        "latency_ms": {"p50": round(p50, 1), "p95": round(p95, 1)},
        "cost_usd": {
            "total": round(cost_total, 6),
            "per_1000_candidates": round(cost_total / n * 1000, 6) if n else 0.0,
        },
        "calls": dict(counters),
        "probabilities": {rid: round(pp, 4) for rid, (pp, _lat) in results.items()},
        "failed_ids": failed,
    }  # calls 计数（retries/http_429）见 stdout 汇总，不入档
    report_path = path.parent / "jev_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    gates_met = [agreement >= 0.90, kappa >= 0.75, fn_rate <= 0.02, p95 < 1000]
    passed = n >= 30 and all(gates_met) and counters.get("http_429", 0) < 5
    print(
        "\n── 对拍结果（对照 Phase 0 门禁）──\n"
        f"样本 {n}（误触 {tn + fp} / 真错误 {n_real}；失败 {len(failed)} 不计入）\n"
        f"agreement {agreement:.4f}（≥0.90）｜κ {kappa:.4f}（≥0.75）｜漏报率 {fn_rate:.4f}（红线≤0.02）\n"
        f"P50/P95 {p50:.0f}/{p95:.0f} ms（门禁 <1000）｜429 {counters.get('http_429', 0)} 次"
        f"｜成本 ${cost_total:.4f}（≈ ${report['cost_usd']['per_1000_candidates']:.4f}/千候选）\n"
        f"报告 {report_path}"
    )
    print("✅ 满足门禁判据" if passed else "❌ 未满足门禁判据（样本量 <30 时仅作参考）")
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("command", nargs="?", choices=["smoke", "export", "run"], default="smoke")
    parser.add_argument("--source", nargs="+", help="export：课件样本目录（可多个，合并导出）")
    parser.add_argument("--candidates", help="run：已标注候选 JSONL")
    parser.add_argument("--limit", type=int, default=0, help="run：只取前 N 条已标注候选")
    parser.add_argument("--concurrency", type=int, default=8, help="run：并发上限")
    parser.add_argument("--timeout", type=float, default=30.0, help="单次 HTTP 超时（秒）")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="判定模型 ID（换模型须重跑对拍）")
    parser.add_argument("--api-url", default=DEFAULT_API_URL, help="Noul 决策端点 URL")
    parser.add_argument(
        "--drop-below",
        type=float,
        default=DEFAULT_DROP_BELOW,
        help="阈值分带下界（对齐 drop_below 语义）",
    )
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    if args.command == "export":
        return _cmd_export(args)
    return _cmd_run(args) if args.command == "run" else _cmd_smoke(args)


if __name__ == "__main__":
    raise SystemExit(main())
