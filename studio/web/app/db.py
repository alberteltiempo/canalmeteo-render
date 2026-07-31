"""Registro local de trabajos en nimbus (SQLite).

Sólo guarda el ciclo de vida del lado web (awaiting_upload → submitted) y los
metadatos para listar. El estado real de procesado se lee de status.json en Spaces.
"""
from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from typing import Optional

from studio.shared import config as cfg
from studio.shared.schemas import now_iso

_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    job_id          TEXT PRIMARY KEY,
    source_filename TEXT NOT NULL,
    source_key      TEXT NOT NULL,
    language        TEXT NOT NULL,
    script_text     TEXT NOT NULL DEFAULT '',
    operations      TEXT NOT NULL,   -- JSON
    web_state       TEXT NOT NULL,   -- awaiting_upload | submitted
    created_at      TEXT NOT NULL
);
"""


@contextmanager
def _conn():
    os.makedirs(os.path.dirname(cfg.DB_PATH), exist_ok=True)
    con = sqlite3.connect(cfg.DB_PATH)
    con.row_factory = sqlite3.Row
    try:
        yield con
        con.commit()
    finally:
        con.close()


def init() -> None:
    with _conn() as con:
        con.executescript(_SCHEMA)


def create_job(job_id, source_filename, source_key, language, script_text, operations) -> None:
    with _conn() as con:
        con.execute(
            "INSERT INTO jobs (job_id, source_filename, source_key, language, script_text, operations, web_state, created_at)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (job_id, source_filename, source_key, language, script_text or "", json.dumps(operations),
             "awaiting_upload", now_iso()),
        )


def mark_submitted(job_id: str) -> None:
    with _conn() as con:
        con.execute("UPDATE jobs SET web_state='submitted' WHERE job_id=?", (job_id,))


def get_job(job_id: str) -> Optional[dict]:
    with _conn() as con:
        row = con.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
        return _row(row) if row else None


def list_jobs(limit: int = 100) -> list[dict]:
    with _conn() as con:
        rows = con.execute(
            "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [_row(r) for r in rows]


def _row(r: sqlite3.Row) -> dict:
    d = dict(r)
    d["operations"] = json.loads(d["operations"])
    return d
