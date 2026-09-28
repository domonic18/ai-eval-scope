"""判定专线高置信误触过滤层单测 — 替身 client 全离线（禁联网纪律）。

覆盖：阈值分带（DROP/ESCALATE 边界）/ 单候选失败升级 / 整体故障全量升级 /
并发上限 / 问题组装与模板覆盖 / 证据报告 schema 与凭证零泄漏 / 预筛 mixin
（未启用逐字节等价、审计字段就地写回、证据落盘容错）/ _init_decision_client 接线。
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

import pytest

from agent_eval.config import EVALUATOR_DEFAULTS
from agent_eval.config.llm import LLMConfig, ProviderConfig
from agent_eval.core.exceptions import DecisionError
from agent_eval.evaluation.decision_filter import DEFAULT_CRITERIA, DecisionFactFilter
from agent_eval.evaluation.evaluators.commonsense._decision_precheck import (
    DECISION_EVIDENCE_FILENAME,
    InfoAccuracyDecisionPrecheck,
)
from agent_eval.llm import DecisionAnswer, NoulQuestion
from agent_eval.orchestrator.orchestrator import _init_decision_client


class _StubDecisionClient:
    """DecisionClient 替身：按预设函数返回概率（或抛异常）；记录调用与并发峰值。"""

    def __init__(self, fn: Any, model: str = "decision-stub-1") -> None:
        self._fn = fn
        self.model = model  # DecisionFactFilter 回退标签读取的同名属性
        self.calls: list[tuple[NoulQuestion, dict]] = []
        self.max_inflight = 0
        self._inflight = 0
        self._lock = threading.Lock()

    def noul(self, question: NoulQuestion, state: dict) -> DecisionAnswer:
        with self._lock:
            self.calls.append((question, dict(state)))
            self._inflight += 1
            self.max_inflight = max(self.max_inflight, self._inflight)
        try:
            time.sleep(0.005)  # 撑开并发窗口
            p = self._fn(question, state)
            if isinstance(p, Exception):
                raise p
            return DecisionAnswer(p_yes=p, question_name=question.name, model=self.model)
        finally:
            with self._lock:
                self._inflight -= 1


def _candidates(n: int) -> list[dict[str, Any]]:
    return [
        {"index": i, "file": f"p{i}.html", "message": f"疑似错误 {i}", "context": f"原文 {i}"}
        for i in range(n)
    ]


class TestThresholdBand:
    """阈值分带：p < drop_below → DROP；边界与不确定带 → ESCALATE。"""

    def test_low_probability_dropped(self) -> None:
        client = _StubDecisionClient(lambda _q, _s: 0.04)
        report = DecisionFactFilter(client, drop_below=0.50).run(_candidates(1))
        assert report.counts == {"total": 1, "dropped": 1, "escalated": 0}
        assert report.items[0]["decision"] == "drop"
        assert report.items[0]["probability"] == 0.04

    @pytest.mark.parametrize("p", [0.50, 0.51, 0.79, 0.97])
    def test_boundary_and_above_escalate(self, p: float) -> None:
        """边界 p == drop_below 不剔除（严格小于），不确定带与真错误带全升级。"""
        client = _StubDecisionClient(lambda _q, _s: p)
        report = DecisionFactFilter(client, drop_below=0.50).run(_candidates(1))
        assert report.items[0]["decision"] == "escalate"
        assert report.counts["dropped"] == 0

    def test_mixed_bands_counted(self) -> None:
        probs = [0.04, 0.90, 0.20, 0.60]
        client = _StubDecisionClient(lambda _q, s: probs[int(s["claim"].split()[-1])])
        report = DecisionFactFilter(client, drop_below=0.50).run(_candidates(4))
        assert report.counts == {"total": 4, "dropped": 2, "escalated": 2}


class TestFailureEscalation:
    """降级语义：单候选失败升级（召回优先）；整体故障 = 全量升级。"""

    def test_single_candidate_error_escalates_others_proceed(self) -> None:
        def fn(_q: NoulQuestion, s: dict) -> Any:
            return DecisionError("网络中断") if s["claim"].endswith("1") else 0.90

        client = _StubDecisionClient(fn)
        report = DecisionFactFilter(client).run(_candidates(3))
        assert report.counts == {"total": 3, "dropped": 0, "escalated": 3}
        failed = next(it for it in report.items if it["index"] == 1)
        assert failed["probability"] is None  # 失败项无概率，绝不 DROP

    def test_total_failure_escalates_all(self) -> None:
        client = _StubDecisionClient(lambda _q, _s: DecisionError("鉴权失效"))
        report = DecisionFactFilter(client).run(_candidates(2))
        assert report.counts == {"total": 2, "dropped": 0, "escalated": 2}

    def test_unexpected_exception_propagates(self) -> None:
        """非 DecisionError 的意外异常不由 filter 吞——由上层 mixin 兜底全量升级。"""
        client = _StubDecisionClient(lambda _q, _s: RuntimeError("bug"))
        with pytest.raises(RuntimeError):
            DecisionFactFilter(client).run(_candidates(1))


class TestConcurrencyCap:
    def test_max_inflight_bounded(self) -> None:
        barrier = threading.Barrier(3, timeout=10)  # 恰满 3 才放行，小于 3 即挂死失败

        def fn(_q: NoulQuestion, _s: dict) -> float:
            barrier.wait()
            return 0.10

        client = _StubDecisionClient(fn)
        report = DecisionFactFilter(client, max_concurrency=3).run(_candidates(9))
        assert report.counts["dropped"] == 9
        assert client.max_inflight <= 3


class TestQuestionAssembly:
    def test_state_and_default_question(self) -> None:
        client = _StubDecisionClient(lambda _q, _s: 0.10)
        DecisionFactFilter(client).run(_candidates(1))
        question, state = client.calls[0]
        assert state == {"text": "原文 0", "claim": "疑似错误 0"}
        assert question.name == "is_real_error"
        assert "疑似事实错误" in question.instructions
        assert question.criteria == DEFAULT_CRITERIA

    def test_template_override(self) -> None:
        client = _StubDecisionClient(lambda _q, _s: 0.10)
        flt = DecisionFactFilter(client, instructions="自定义判定正文")
        flt.run(_candidates(1))
        question, _ = client.calls[0]
        assert question.instructions == "自定义判定正文"
        assert question.criteria == DEFAULT_CRITERIA  # criteria 不随模板覆盖


class TestStageReport:
    def test_evidence_schema_no_secret(self) -> None:
        client = _StubDecisionClient(lambda _q, _s: 0.04, model="decision-1-20260917")
        report = DecisionFactFilter(client, drop_below=0.50).run(_candidates(2))
        payload = report.to_evidence()
        assert set(payload) == {"enabled", "model", "drop_below", "counts", "items"}
        assert payload["model"] == "decision-1-20260917"  # 服务端 resolved 快照优先
        assert set(payload["counts"]) == {"total", "dropped", "escalated"}
        assert all(
            set(it) <= {"index", "probability", "decision", "latency_ms", "model"}
            for it in payload["items"]
        )
        assert "sk-" not in json.dumps(payload)  # 凭证零泄漏


class _Host(InfoAccuracyDecisionPrecheck):
    """最小组合主体：仅 mixin 依赖的成员（params + 上下文提取）。"""

    def __init__(self, params: dict | None = None) -> None:
        self.params = params or {}

    def _extract_finding_context(self, f: dict, file_texts: dict) -> str:
        return file_texts.get(f.get("file", ""), "")


def _findings(n: int) -> list[dict[str, Any]]:
    return [
        {"file": f"p{i}.html", "message": f"疑似错误 {i}", "severity": "error"} for i in range(n)
    ]


class TestApplyDecisionFilter:
    """mixin 预筛：未启用逐字节等价 / 启用剔除与审计写回 / 故障兜底。"""

    def _run(self, host: _Host, findings: list[dict], context: dict, tmp_path: Path) -> list[dict]:
        texts = {f"p{i}.html": f"原文 {i}" for i in range(len(findings))}
        return host._apply_decision_filter(findings, texts, context, tmp_path)

    def test_disabled_builds_candidates_verbatim(self, tmp_path: Path) -> None:
        """默认关：候选与直构完全一致、零判定调用、零证据落盘（逐字节等价路径）。"""
        host = _Host()  # decision_enabled 默认 False
        findings = _findings(2)
        out = self._run(
            host, findings, {"decision_client": _StubDecisionClient(lambda _q, _s: 0.01)}, tmp_path
        )
        assert [c["index"] for c in out] == [0, 1]
        assert all("_decision_filtered" not in f for f in findings)
        assert not (tmp_path / DECISION_EVIDENCE_FILENAME).exists()

    def test_missing_client_treated_as_disabled(self, tmp_path: Path) -> None:
        host = _Host({"decision_enabled": True})
        out = self._run(host, _findings(1), {}, tmp_path)  # context 无 decision_client
        assert [c["index"] for c in out] == [0]

    def test_enabled_drops_and_writes_audit_fields(self, tmp_path: Path) -> None:
        def fn(_q: NoulQuestion, s: dict) -> Any:
            return (
                0.04
                if s["claim"].endswith("0")
                else (DecisionError("超时") if s["claim"].endswith("1") else 0.80)
            )

        client = _StubDecisionClient(fn)
        host = _Host({"decision_enabled": True})
        findings = _findings(3)
        out = self._run(host, findings, {"decision_client": client}, tmp_path)
        # 剔除 0（高置信误触）；1（失败）与 2（不确定/真错误带）升级送 LLM
        assert [c["index"] for c in out] == [1, 2]
        assert findings[0]["_decision_filtered"] is True
        assert findings[0]["_decision_probability"] == 0.04
        assert (
            "_decision_filtered" not in findings[1] and "_decision_probability" not in findings[1]
        )
        # 证据落盘：counts 对齐，剔除候选可溯源
        evidence = json.loads((tmp_path / DECISION_EVIDENCE_FILENAME).read_text(encoding="utf-8"))
        assert evidence["counts"] == {"total": 3, "dropped": 1, "escalated": 2}
        assert evidence["items"][0]["index"] == 0

    def test_unexpected_filter_failure_escalates_all(self, tmp_path: Path) -> None:
        """过滤层意外异常 → 全量升级（等价未启用），不抛出。"""
        client = _StubDecisionClient(lambda _q, _s: RuntimeError("bug"))
        host = _Host({"decision_enabled": True})
        findings = _findings(2)
        out = self._run(host, findings, {"decision_client": client}, tmp_path)
        assert [c["index"] for c in out] == [0, 1]
        assert all("_decision_filtered" not in f for f in findings)

    def test_evidence_write_failure_does_not_block(self, tmp_path: Path) -> None:
        """落盘失败（目录不可写）仅降级，不影响过滤结果。"""
        evidence_file = tmp_path / "not-a-dir"  # 用「文件作为目录」制造写失败
        evidence_file.write_text("x", encoding="utf-8")
        host = _Host({"decision_enabled": True})
        client = _StubDecisionClient(lambda _q, _s: 0.04)
        out = host._apply_decision_filter(
            _findings(1),
            {"p0.html": "原文 0"},
            {"decision_client": client},
            evidence_file,  # 类型正确但 write_text/mkdir 必失败
        )
        assert out == []  # 剔除仍生效


class TestInitDecisionClient:
    """编排接线：decision 线路缺失/非法 → None（静默禁用）；超时按默认覆写。"""

    @staticmethod
    def _llm_config(with_decision: bool = True, model: str = "typesafe/jev-1.13") -> LLMConfig:
        providers: dict[str, ProviderConfig] = {
            "text": ProviderConfig(
                provider="anthropic", model="m-1", api_key="sk-x", base_url="https://x"
            )
        }
        if with_decision:
            providers["decision"] = ProviderConfig(
                provider="noul",
                model=model,
                api_key="sk-decision-test",
                base_url="https://router.test/api",
                timeout_sec=180.0,
            )
        return LLMConfig(default="text", providers=providers)

    def test_builds_client_with_timeout_override(self) -> None:
        client = _init_decision_client(self._llm_config())
        assert client is not None
        assert client.name == "decision"
        assert client.model == "typesafe/jev-1.13"
        assert client._config.timeout_sec == EVALUATOR_DEFAULTS.decision_timeout_sec  # 覆写生效

    def test_missing_decision_role_returns_none(self) -> None:
        assert _init_decision_client(self._llm_config(with_decision=False)) is None

    def test_none_config_returns_none(self) -> None:
        assert _init_decision_client(None) is None

    def test_non_llm_config_returns_none(self) -> None:
        assert _init_decision_client(object()) is None

    def test_swap_model_without_code_change(self) -> None:
        """零代码换模型：同 noul 协议换 model 字段，客户端原样构造（通用性契约）。"""
        client = _init_decision_client(self._llm_config(model="typesafe/other-fast-2.0"))
        assert client is not None
        assert client.model == "typesafe/other-fast-2.0"
