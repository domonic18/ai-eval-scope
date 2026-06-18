"""IngestionClient：HTTP + HMAC 签名 + presigned 制品上传 + 重试退避。

签名算法与后端 apiKeyAuth（web/backend/src/infra/crypto.ts）严格一致：
    canonical = METHOD + "\n" + PATH + "\n" + sha256(body)
    signature  = hex(HMAC_SHA256(secret, canonical))
    Authorization: "Eval " + public_key + ":" + signature

重试：429/5xx 指数退避，尊重 Retry-After。
"""

from __future__ import annotations

import hashlib
import hmac
import json
import random
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from agent_eval.core.logging import get_logger
from agent_eval.observability.config import ObservabilityConfig


class IngestionError(Exception):
    """不可重试的摄取错误（如 4xx 鉴权/校验/禁止）。"""

    def __init__(self, message: str, *, status: int | None = None, body: Any = None) -> None:
        super().__init__(message)
        self.status = status
        self.body = body


@dataclass
class IngestResponse:
    """后端 /ingest 响应（202 部分接受）。"""

    accepted: int
    duplicates: int
    errors: list[dict[str, Any]]
    raw: dict[str, Any]


def sign(method: str, path: str, body: bytes, secret: str) -> str:
    """计算 HMAC-SHA256 签名（与后端一致）。"""
    body_hash = hashlib.sha256(body).hexdigest()
    canonical = f"{method.upper()}\n{path}\n{body_hash}"
    return hmac.new(secret.encode("utf-8"), canonical.encode("utf-8"), hashlib.sha256).hexdigest()


def _path_of(url: str) -> str:
    """从绝对 URL 取 path（签名只用 path，不含 host/query）。"""
    from urllib.parse import urlparse

    p = urlparse(url)
    return p.path or "/"


class IngestionClient:
    """平台摄取客户端（线程安全；每次调用独立 httpx 请求）。"""

    def __init__(self, config: ObservabilityConfig) -> None:
        self.cfg = config
        self.log = get_logger("observability.client")

    # ── 摄取 ──
    def post_ingest(self, events: list[dict[str, Any]]) -> IngestResponse:
        """POST /api/public/ingest（批量事件）。失败抛 IngestionError 或 httpx 异常。"""
        body = json.dumps(
            {"schema_version": "1.0", "project_id": self.cfg.project, "events": events},
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        return self._signed_post(self.cfg.ingest_url, body, parse_ingest=True)

    def health(self) -> dict[str, Any]:
        """GET /health 启动自检（无签名）。失败抛异常。"""
        with httpx.Client(timeout=self.cfg.timeout_sec) as client:
            resp = client.get(self.cfg.health_url)
            resp.raise_for_status()
            return resp.json()

    # ── 制品 presigned 上传 ──
    def presign_put(self, request: dict[str, Any]) -> dict[str, Any]:
        """POST /api/public/artifacts/url 申请 presigned PUT。返回 {object_key, upload_url, headers, expires_at}。"""
        body = json.dumps(request, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        resp = self._signed_post(self.cfg.artifacts_url, body, parse_ingest=False)
        return resp  # type: ignore[return-value]

    def upload_file(
        self, local_path: Path, presigned: dict[str, Any], content_type: str
    ) -> dict[str, Any]:
        """PUT 本地文件到 presigned URL。返回 {md5, size}。"""
        data = local_path.read_bytes()
        headers = dict(presigned.get("headers") or {})
        headers.setdefault("Content-Type", content_type)
        with httpx.Client(timeout=self.cfg.timeout_sec) as client:
            resp = client.put(presigned["upload_url"], content=data, headers=headers)
            resp.raise_for_status()
        return {"md5": hashlib.md5(data).hexdigest(), "size": len(data)}

    # ── 内部：带签名的 POST + 退避重试 ──
    def _signed_post(self, url: str, body: bytes, *, parse_ingest: bool) -> Any:
        path = _path_of(url)
        signature = sign("POST", path, body, self.cfg.secret_key)
        headers = {
            "Authorization": f"Eval {self.cfg.public_key}:{signature}",
            "Content-Type": "application/json",
            "X-Eval-Client": self.cfg.client_version,
        }

        last_exc: Exception | None = None
        for attempt in range(self.cfg.max_retries + 1):
            try:
                with httpx.Client(timeout=self.cfg.timeout_sec) as client:
                    resp = client.post(url, content=body, headers=headers)
            except httpx.HTTPError as exc:
                last_exc = exc
                self._backoff(attempt, None)
                continue

            # 成功或不可重试的 4xx
            if resp.status_code < 300:
                return self._parse(resp) if parse_ingest else resp.json()
            if (
                resp.status_code in (401, 403)
                or 400 <= resp.status_code < 500
                and resp.status_code != 429
            ):
                # 4xx（鉴权/禁止/校验/版本不支持）不重试
                raise IngestionError(
                    f"ingest rejected: HTTP {resp.status_code}",
                    status=resp.status_code,
                    body=self._safe_json(resp),
                )
            # 429 / 5xx → 退避重试
            last_exc = IngestionError(
                f"retryable: HTTP {resp.status_code}", status=resp.status_code
            )
            if attempt >= self.cfg.max_retries:
                break
            self._backoff(attempt, resp)

        raise last_exc or IngestionError("ingest failed")

    def _backoff(self, attempt: int, resp: httpx.Response | None) -> None:
        retry_after = None
        if resp is not None:
            retry_after = resp.headers.get("retry-after")
        if retry_after:
            try:
                time.sleep(min(float(retry_after), self.cfg.backoff_max_sec))
                return
            except ValueError:
                pass
        base = self.cfg.backoff_base_sec * (2**attempt)
        jitter = random.uniform(0, base / 2)
        time.sleep(min(base + jitter, self.cfg.backoff_max_sec))

    @staticmethod
    def _safe_json(resp: httpx.Response) -> Any:
        try:
            return resp.json()
        except Exception:
            return resp.text

    @staticmethod
    def _parse(resp: httpx.Response) -> IngestResponse:
        data = resp.json()
        return IngestResponse(
            accepted=int(data.get("accepted", 0)),
            duplicates=int(data.get("duplicates", 0)),
            errors=list(data.get("errors", [])),
            raw=data,
        )
