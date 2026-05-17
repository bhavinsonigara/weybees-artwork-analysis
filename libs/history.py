from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_lock = threading.Lock()
_path = Path(os.getenv("SQLITE_PATH", "./data/history.sqlite3"))


def _init() -> None:
    _path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS analyses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                task TEXT NOT NULL,
                image_sha TEXT NOT NULL,
                result_json TEXT NOT NULL
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_task_sha ON analyses(task, image_sha)")
        conn.commit()


_init()


def record(task: str, image_sha: str, result: Any) -> None:
    try:
        with _lock, sqlite3.connect(_path) as conn:
            conn.execute(
                "INSERT INTO analyses (created_at, task, image_sha, result_json) VALUES (?, ?, ?, ?)",
                (
                    datetime.now(timezone.utc).isoformat(),
                    task,
                    image_sha,
                    json.dumps(result),
                ),
            )
            conn.commit()
    except Exception as exc:
        log.warning("history write failed task=%s sha=%s err=%s", task, image_sha, exc)
