from pathlib import Path

from labwatch_agent.queue import EventQueue


def test_event_queue_roundtrip(tmp_path: Path):
    q = EventQueue(tmp_path / "q.db")
    q.push("event", {"event_type": "RAM_REMOVED"})
    q.push("log", {"message": "offline"})
    assert len(q) == 2
    batch = q.pop_batch()
    assert len(batch) == 2
    q.delete([batch[0][0]])
    assert len(q) == 1
