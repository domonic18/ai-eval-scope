"""observability 配置 / HMAC 签名 / 离线队列 单测。"""

from __future__ import annotations

import hashlib
import hmac
import time
from pathlib import Path

import pytest

from agent_eval.observability.client import IngestionClient, sign
from agent_eval.observability.config import load_config
from agent_eval.observability.queue import IngestQueue


# ── 配置 ──
def test_config_disabled_without_credentials(tmp_path: Path):
    cfg = load_config(workspace=tmp_path, env={})
    assert cfg.enabled is False
    assert cfg.has_credentials() is False


def test_config_enabled_with_credentials_and_upload(tmp_path: Path):
    cfg = load_config(
        workspace=tmp_path,
        env={
            "AGENT_EVAL_HOST": "https://platform.example.com",
            "AGENT_EVAL_PUBLIC_KEY": "pk-eval-abc",
            "AGENT_EVAL_SECRET_KEY": "sk-eval-xyz",
            "AGENT_EVAL_UPLOAD": "true",
            "AGENT_EVAL_PROJECT": "demo",
        },
    )
    assert cfg.enabled is True
    assert cfg.has_credentials() is True
    assert cfg.ingest_url == "https://platform.example.com/api/public/ingest"
    assert cfg.artifacts_url == "https://platform.example.com/api/public/artifacts/url"
    assert cfg.project == "demo"
    assert cfg.queue_dir == tmp_path / ".ingest_queue"


def test_config_upload_override(tmp_path: Path):
    # 有凭据但 env 未开 upload → disabled；CLI --upload 覆盖 → enabled
    env = {"AGENT_EVAL_PUBLIC_KEY": "pk", "AGENT_EVAL_SECRET_KEY": "sk"}
    assert load_config(workspace=tmp_path, env=env).enabled is False
    assert load_config(workspace=tmp_path, env=env, upload_override=True).enabled is True


# ── HMAC 签名（与后端 crypto.ts 一致）──
def test_sign_matches_canonical_formula():
    """独立按公式重算，验证 sign() 实现（METHOD\\nPATH\\nsha256(body)）。"""
    method, path, secret = "POST", "/api/public/ingest", "the-secret"
    body = b'{"schema_version":"1.0","events":[]}'
    expected_canon = f"{method}\n{path}\n{hashlib.sha256(body).hexdigest()}"
    expected = hmac.new(secret.encode(), expected_canon.encode(), hashlib.sha256).hexdigest()
    assert sign(method, path, body, secret) == expected


def test_sign_deterministic_and_method_uppercased():
    body = b"x"
    s1 = sign("post", "/p", body, "k")
    s2 = sign("POST", "/p", body, "k")
    assert s1 == s2  # 方法大小写归一


# ── 离线队列 ──
def test_queue_enqueue_and_size(tmp_path: Path):
    q = IngestQueue(tmp_path / "q")
    assert q.size().pending == 0
    q.enqueue([{"event_id": "e1", "type": "run", "data": {}}])
    q.enqueue([{"event_id": "e2", "type": "run", "data": {}}])
    assert q.size().pending == 2
    assert q.size().dead_letter == 0


class _FakeClient:
    """伪 IngestionClient：可控制第 N 次成功/失败。"""

    def __init__(self, *, fail_times: int = 0, fail_exc: BaseException | None = None) -> None:
        self.fail_times = fail_times
        self.calls = 0
        self.fail_exc = fail_exc or ConnectionError("network down")

    def post_ingest(self, payload):  # noqa: ANN001
        self.calls += 1
        if self.calls <= self.fail_times:
            raise self.fail_exc
        return {"accepted": len(payload), "duplicates": 0, "errors": []}


def test_queue_replay_sends_and_deletes(tmp_path: Path):
    q = IngestQueue(tmp_path / "q", max_attempts=5)
    q.enqueue([{"event_id": "e1"}])
    q.enqueue([{"event_id": "e2"}])
    client = _FakeClient(fail_times=0)
    res = q.replay(client, batch=10)
    assert res["sent"] == 2
    assert q.size().pending == 0


def test_queue_replay_requeues_on_retryable_failure(tmp_path: Path):
    q = IngestQueue(tmp_path / "q", max_attempts=5, backoff_base_sec=0)
    q.enqueue([{"event_id": "e1"}])
    client = _FakeClient(fail_times=1, fail_exc=ConnectionError("transient"))  # 首次失败，二次成功
    assert q.replay(client, batch=10)["sent"] == 0
    # 入队后 next_retry_at 在未来（指数退避）→ 推进时间后重放成功
    res2 = q.replay(client, batch=10, now=time.time() + 3600)
    assert res2["sent"] == 1
    assert q.size().pending == 0


def test_queue_dead_letter_after_max_attempts(tmp_path: Path):
    q = IngestQueue(tmp_path / "q", max_attempts=2, backoff_base_sec=0)
    q.enqueue([{"event_id": "e1"}])
    client = _FakeClient(fail_times=99, fail_exc=ConnectionError("always fails"))
    q.replay(client, batch=10, now=time.time() + 1)
    q.replay(client, batch=10, now=time.time() + 100)  # attempts 达上限 → 死信
    assert q.size().pending == 0
    assert q.size().dead_letter == 1


def test_queue_non_retryable_4xx_goes_straight_to_dead_letter(tmp_path: Path):
    from agent_eval.observability.client import IngestionError

    q = IngestQueue(tmp_path / "q", max_attempts=10)
    q.enqueue([{"event_id": "e1"}])
    client = _FakeClient(fail_times=99, fail_exc=IngestionError("forbidden", status=403))
    res = q.replay(client, batch=10)
    assert res["dead_lettered"] == 1
    assert q.size().dead_letter == 1
