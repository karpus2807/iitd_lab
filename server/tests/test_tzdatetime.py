from datetime import datetime, timezone

from app.db import TZDateTime


class _Dialect:
    def __init__(self, name: str):
        self.name = name


def test_bind_param_strips_tzinfo_for_asyncpg_timestamp():
    col = TZDateTime()
    aware = datetime(2026, 9, 15, 5, 1, 57, 967200, tzinfo=timezone.utc)
    bound = col.process_bind_param(aware, _Dialect("postgresql"))
    assert bound.tzinfo is None
    assert bound == datetime(2026, 9, 15, 5, 1, 57, 967200)


def test_result_value_is_utc_aware():
    col = TZDateTime()
    naive = datetime(2026, 9, 15, 5, 1, 57)
    got = col.process_result_value(naive, _Dialect("postgresql"))
    assert got.tzinfo == timezone.utc
    assert got.hour == 5
