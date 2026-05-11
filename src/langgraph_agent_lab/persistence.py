"""Checkpointer adapter."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any


def build_checkpointer(kind: str = "memory", database_url: str | None = None) -> Any | None:
    """Return a LangGraph checkpointer."""
    if kind == "none":
        return None
    if kind == "memory":
        from langgraph.checkpoint.memory import MemorySaver

        return MemorySaver()
    if kind == "sqlite":
        try:
            from langgraph.checkpoint.sqlite import SqliteSaver
        except ImportError as exc:
            raise RuntimeError(
                "SQLite checkpointer requires: "
                "pip install langgraph-checkpoint-sqlite"
            ) from exc

        database_path = Path(database_url or "checkpoints.db")
        database_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(database_path, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        return SqliteSaver(conn=conn)
    raise ValueError(f"Unknown checkpointer kind: {kind}")
