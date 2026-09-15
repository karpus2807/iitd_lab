from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any


class EventQueue:
    """Durable buffer for critical events while the server is unreachable."""

    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS queue (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    kind TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    created_at REAL NOT NULL
                )"""
            )

    def push(self, kind: str, payload: dict[str, Any]) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO queue(kind, payload, created_at) VALUES (?, ?, ?)",
                (kind, json.dumps(payload), time.time()),
            )

    def pop_batch(self, limit: int = 50) -> list[tuple[int, str, dict[str, Any]]]:
        with self._connect() as conn:
            rows = conn.execute("SELECT id, kind, payload FROM queue ORDER BY id ASC LIMIT ?", (limit,)).fetchall()
        return [(r[0], r[1], json.loads(r[2])) for r in rows]

    def delete(self, ids: list[int]) -> None:
        if not ids:
            return
        q = ",".join("?" for _ in ids)
        with self._connect() as conn:
            conn.execute(f"DELETE FROM queue WHERE id IN ({q})", ids)

    def __len__(self) -> int:
        with self._connect() as conn:
            return int(conn.execute("SELECT COUNT(*) FROM queue").fetchone()[0])
