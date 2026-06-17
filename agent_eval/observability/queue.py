"""离线队列（SQLite）+ 重放 + 死信（docs/arch/09 §8.4）。

发送失败（网络/5xx/429）的事件入队；下次 eval 启动或后台线程重放。
重放时重复发送是安全的——后端按 event_id 幂等去重（§7.2），故「发了就算成功」。

队列存储：<queue_dir>/queue.sqlite，表 pending_events(id, payload, attempts, last_error, next_retry_at)。
退避：指数退避 + 抖动；超过 max_attempts → 移入 dead_letter 表（保留审计）。
"""

from __future__ import annotations

import json
import random
import sqlite3
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent_eval.core.logging import get_logger
from agent_eval.observability.client import IngestionClient, IngestionError

_SCHEMA = """
CREATE TABLE IF NOT EXISTS pending_events (
    id            TEXT PRIMARY KEY,
    payload       TEXT NOT NULL,
    attempts      INTEGER NOT NULL DEFAULT 0,
    last_error    TEXT,
    next_retry_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_pending_next_retry ON pending_events(next_retry_at);

CREATE TABLE IF NOT EXISTS dead_letter (
    id         TEXT PRIMARY KEY,
    payload    TEXT NOT NULL,
    attempts   INTEGER NOT NULL,
    last_error TEXT,
    moved_at   REAL NOT NULL
);
"""


@dataclass
class QueueStats:
    pending: int
    dead_letter: int


class IngestQueue:
    """SQLite 持久化离线队列。每个 payload 是一批待发送事件（与 /ingest 请求体 events 同构）。"""

    def __init__(
        self, queue_dir: Path, *, max_attempts: int = 10, backoff_base_sec: float = 2.0
    ) -> None:
        self.queue_dir = queue_dir
        self.max_attempts = max_attempts
        self.backoff_base_sec = backoff_base_sec
        self.log = get_logger("observability.queue")
        self.queue_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = queue_dir / "queue.sqlite"
        self._init_schema()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._conn() as conn:
            conn.executescript(_SCHEMA)
            conn.commit()

    # ── 入队 ──
    def enqueue(self, payload: list[dict[str, Any]]) -> str:
        """一批事件入队（POST 失败时调用）。返回行 id。"""
        row_id = uuid.uuid4().hex
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO pending_events(id, payload, attempts, last_error, next_retry_at) VALUES (?,?,?,?,?)",
                (row_id, json.dumps(payload, ensure_ascii=False), 0, None, time.time()),
            )
            conn.commit()
        self.log.info("queue.enqueue", row_id=row_id, events=len(payload))
        return row_id

    def size(self) -> QueueStats:
        with self._conn() as conn:
            pending = conn.execute("SELECT COUNT(*) AS n FROM pending_events").fetchone()["n"]
            dead = conn.execute("SELECT COUNT(*) AS n FROM dead_letter").fetchone()["n"]
        return QueueStats(pending=int(pending), dead_letter=int(dead))

    # ── 重放 ──
    def replay(
        self, client: IngestionClient, *, batch: int = 100, now: float | None = None
    ) -> dict[str, int]:
        """重放到期的待发事件。返回 {sent, requeued, dead_lettered}。

        - 发送成功 → 出队（后端按 event_id 幂等，重复发送也安全）。
        - 可重试失败 → attempts++，更新 next_retry_at（指数退避）。
        - 超过 max_attempts → 移入死信。
        """
        now = now if now is not None else time.time()
        sent = requeued = dead_lettered = 0

        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM pending_events WHERE next_retry_at <= ? ORDER BY next_retry_at ASC LIMIT ?",
                (now, batch),
            ).fetchall()

        for row in rows:
            payload: list[dict[str, Any]] = json.loads(row["payload"])
            try:
                client.post_ingest(payload)
                sent += 1
                self._delete(row["id"])
                self.log.info("queue.replay.sent", row_id=row["id"], events=len(payload))
            except IngestionError as exc:
                # 不可重试的 4xx（鉴权/禁止/校验）→ 直接死信（重试无意义）
                self._to_dead_letter(row, exc)
                dead_lettered += 1
                self.log.warning("queue.replay.dead_letter", row_id=row["id"], error=str(exc))
            except Exception as exc:  # noqa: BLE001 — 网络/5xx/超时等可重试
                attempts = int(row["attempts"]) + 1
                if attempts >= self.max_attempts:
                    self._to_dead_letter(row, exc)
                    dead_lettered += 1
                    self.log.warning(
                        "queue.replay.dead_letter", row_id=row["id"], attempts=attempts
                    )
                else:
                    self._requeue(row["id"], attempts, str(exc))
                    requeued += 1
                    self.log.info("queue.replay.requeued", row_id=row["id"], attempts=attempts)

        return {"sent": sent, "requeued": requeued, "dead_lettered": dead_lettered}

    # ── 内部 ──
    def _requeue(self, row_id: str, attempts: int, error: str) -> None:
        base = self.backoff_base_sec * (2 ** (attempts - 1))
        jitter = random.uniform(0, base / 2)
        next_at = time.time() + min(base + jitter, 3600.0)
        with self._conn() as conn:
            conn.execute(
                "UPDATE pending_events SET attempts=?, last_error=?, next_retry_at=? WHERE id=?",
                (attempts, error, next_at, row_id),
            )
            conn.commit()

    def _delete(self, row_id: str) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM pending_events WHERE id=?", (row_id,))
            conn.commit()

    def _to_dead_letter(self, row: sqlite3.Row, exc: BaseException) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO dead_letter(id, payload, attempts, last_error, moved_at) VALUES (?,?,?,?,?)",
                (row["id"], row["payload"], int(row["attempts"]) + 1, str(exc), time.time()),
            )
            conn.execute("DELETE FROM pending_events WHERE id=?", (row["id"],))
            conn.commit()
