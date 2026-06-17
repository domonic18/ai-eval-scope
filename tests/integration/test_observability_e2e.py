"""端到端跨语言验证：Python ResultSink 的 HMAC 签名必须被 Node 后端 apiKeyAuth 接受。

默认跳过（需后端在跑）。显式启用：
    AGENT_EVAL_E2E=1 uv run pytest tests/integration/test_observability_e2e.py

前置：docker compose -f web/docker-compose.yml up -d（postgres+minio）+
      cd web/backend && npm run build && PLATFORM_DATABASE_URL=… node dist/server.js
      （默认指向 http://localhost:3000）
"""

from __future__ import annotations

import os
import uuid

import httpx
import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("AGENT_EVAL_E2E") != "1",
    reason="set AGENT_EVAL_E2E=1 且后端在跑时启用",
)

HOST = os.environ.get("AGENT_EVAL_E2E_HOST", "http://localhost:3000")


@pytest.fixture(scope="module")
def project_key() -> dict[str, str]:
    """注册用户 → 建项目 → 签发 Key，返回 {projectId, publicKey, secretKey, accessToken}。"""
    suffix = uuid.uuid4().hex[:8]
    email = f"e2e_{suffix}@example.com"
    r = httpx.post(
        f"{HOST}/api/v1/auth/register",
        json={"email": email, "password": "password123", "name": "E2E", "orgName": f"Org{suffix}"},
        timeout=30,
    )
    r.raise_for_status()
    access_token = r.json()["access_token"]
    org_id = r.json()["org"]["id"]

    r = httpx.post(
        f"{HOST}/api/v1/orgs/{org_id}/projects",
        headers={"Authorization": f"Bearer {access_token}"},
        json={"name": "Proj", "slug": f"p{suffix}"},
        timeout=30,
    )
    r.raise_for_status()
    project_id = r.json()["project"]["id"]

    r = httpx.post(
        f"{HOST}/api/v1/projects/{project_id}/keys",
        headers={"Authorization": f"Bearer {access_token}"},
        json={"name": "k"},
        timeout=30,
    )
    r.raise_for_status()
    key = r.json()["key"]
    return {"projectId": project_id, "publicKey": key["publicKey"], "secretKey": key["secretKey"]}


def _fake_eval_result(run_id: str):
    """构造一个最小 EvalResult（避免依赖完整评估链路）。"""
    from agent_eval.core.types import ConstraintTier, EvalStatus
    from agent_eval.evaluation.models import (
        ConstraintResult,
        MetricsReport,
        SampleResult,
        StageResult,
    )
    from agent_eval.orchestrator.orchestrator import EvalResult

    report = MetricsReport(
        run_id=run_id,
        total_samples=1,
        dr=0.9,
        cpr=0.7,
        avg_reward=0.6,
        cond_r=0.65,
        avg_time_ms=100,
    )
    sample = SampleResult(sample_id="sample_001", status=EvalStatus.PASS, s_format=1.0, reward=0.8)
    sample.stage_results = {
        "format": StageResult(
            stage_id="format",
            status=EvalStatus.PASS,
            constraint_results=[
                ConstraintResult(
                    constraint_id="format.title",
                    name="has title",
                    tier=ConstraintTier.HARD_GATE,
                    status=EvalStatus.PASS,
                    score=1.0,
                    reason="ok",
                )
            ],
        )
    }
    return EvalResult(report=report, run_id=run_id, samples=[sample])


def test_result_sink_end_to_end(project_key):
    """ResultSink.flush → 后端 202，事件被接受（证明 Python HMAC 与 Node 验签一致 + 链路通）。"""
    from agent_eval.observability.config import load_config
    from agent_eval.observability.sink import ResultSink

    cfg = load_config(
        upload_override=True,
        env={
            "AGENT_EVAL_HOST": HOST,
            "AGENT_EVAL_PUBLIC_KEY": project_key["publicKey"],
            "AGENT_EVAL_SECRET_KEY": project_key["secretKey"],
            "AGENT_EVAL_PROJECT": project_key["projectId"],
        },
    )
    assert cfg.enabled

    sink = ResultSink(cfg)
    run_id = f"e2e_{uuid.uuid4().hex[:8]}"
    report = sink.flush(_fake_eval_result(run_id))

    assert report.enabled
    assert report.error is None, f"flush error: {report.error}"
    assert report.sent >= 2  # run + 至少 1 sample（constraint 也算）
    assert report.queued == 0


def test_cross_project_forbidden(project_key):
    """Python 客户端携带他项目 project_id → 后端 PROJECT_FORBIDDEN（403）。"""
    from agent_eval.observability.client import IngestionClient, IngestionError
    from agent_eval.observability.config import load_config

    cfg = load_config(
        upload_override=True,
        env={
            "AGENT_EVAL_HOST": HOST,
            "AGENT_EVAL_PUBLIC_KEY": project_key["publicKey"],
            "AGENT_EVAL_SECRET_KEY": project_key["secretKey"],
            "AGENT_EVAL_PROJECT": "00000000-0000-0000-0000-000000000000",  # 他项目
        },
    )
    client = IngestionClient(cfg)
    events = [
        {
            "event_id": uuid.uuid4().hex,
            "type": "run",
            "data": {
                "external_run_id": "x",
                "mode": "eval_only",
                "metrics": {
                    "DR": 0.1,
                    "CPR": 0.1,
                    "avg_reward": 0.1,
                    "condR": 0.1,
                    "avg_time_ms": 1,
                },
            },
        }
    ]
    with pytest.raises(IngestionError) as exc_info:
        client.post_ingest(events)
    assert exc_info.value.status == 403
