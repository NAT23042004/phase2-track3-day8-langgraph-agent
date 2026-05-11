import importlib.util

import pytest

from langgraph_agent_lab.persistence import build_checkpointer


def test_build_checkpointer_memory():
    checkpointer = build_checkpointer("memory")
    assert checkpointer is not None


def test_build_checkpointer_none():
    assert build_checkpointer("none") is None


def test_build_checkpointer_invalid_kind():
    with pytest.raises(ValueError, match="Unknown checkpointer kind"):
        build_checkpointer("invalid")


@pytest.mark.skipif(
    importlib.util.find_spec("langgraph.checkpoint.sqlite") is None,
    reason="sqlite checkpointer package not installed",
)
def test_build_checkpointer_sqlite(tmp_path):
    database_path = tmp_path / "checkpoints.db"
    checkpointer = build_checkpointer("sqlite", str(database_path))
    assert checkpointer is not None
    assert database_path.exists()
    if hasattr(checkpointer, "conn"):
        journal_mode = checkpointer.conn.execute("PRAGMA journal_mode;").fetchone()
        assert journal_mode is not None
        assert str(journal_mode[0]).lower() == "wal"
