from pathlib import Path

from labwatch_agent.queue import EventQueue, QueueLogHandler
import logging


def test_event_queue_roundtrip(tmp_path: Path):
    q = EventQueue(tmp_path / "q.db")
    q.push("event", {"event_type": "RAM_REMOVED"})
    q.push("log", {"message": "offline"})
    assert len(q) == 2
    batch = q.pop_batch()
    assert len(batch) == 2
    q.delete([batch[0][0]])
    assert len(q) == 1


def test_queue_log_handler_captures_levels(tmp_path: Path):
    q = EventQueue(tmp_path / "logs.db")
    handler = QueueLogHandler(q)
    log = logging.getLogger("labwatch.agent.testlogs")
    log.handlers = [handler]
    log.setLevel(logging.DEBUG)
    log.propagate = False
    log.debug("dbg")
    log.info("inf")
    log.warning("wrn")
    log.error("err")
    log.critical("crt")
    batch = q.pop_batch(20)
    levels = {item[2]["level"] for item in batch}
    messages = {item[2]["message"] for item in batch}
    assert levels == {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
    assert messages == {"dbg", "inf", "wrn", "err", "crt"}
    assert all(item[2]["details"]["source"] == "agent" for item in batch)
