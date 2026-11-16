"""Regression: inventory_assignments ensure must not crash API startup on legacy rows."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.db import Base, ensure_inventory_assignments_table
from app.models import InventoryItem, Lab, Scholar


def _engine():
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    return eng


def test_ensure_backfill_with_null_assigned_at():
    """create_all makes created_at NOT NULL; legacy assigned_at is often NULL."""
    eng = _engine()
    now = datetime.now(timezone.utc)
    lab_id = uuid4()
    scholar_id = uuid4()
    item_id = uuid4()
    with Session(eng) as db:
        db.add(
            Lab(
                id=lab_id,
                name="Migrate Lab",
                created_at=now,
                updated_at=now,
            )
        )
        db.add(
            Scholar(
                id=scholar_id,
                lab_id=lab_id,
                full_name="Legacy Scholar",
                scholar_id="LEG-1",
                created_at=now,
                updated_at=now,
            )
        )
        db.add(
            InventoryItem(
                id=item_id,
                ic_no="IRD/MIG/NULL-AT",
                item_name="Null assigned_at",
                assigned_to="Legacy Scholar",
                assigned_scholar_id=scholar_id,
                assigned_at=None,
                assign_verify_method="otp",
                status="active",
                created_at=now,
                updated_at=now,
            )
        )
        db.commit()

    with eng.begin() as conn:
        ensure_inventory_assignments_table(conn)

    with eng.connect() as conn:
        row = conn.execute(
            text(
                "SELECT scholar_id, created_at, updated_at, assigned_at FROM inventory_assignments "
                "WHERE inventory_item_id = :iid"
            ),
            {"iid": item_id.hex},
        ).fetchone()
    assert row is not None
    assert row[0] == scholar_id.hex
    assert row[1] is not None
    assert row[2] is not None
    assert row[3] is None  # assigned_at may stay null; timestamps must not


def test_ensure_skips_orphan_assigned_scholar_id():
    eng = _engine()
    now = datetime.now(timezone.utc)
    lab_id = uuid4()
    ghost = uuid4()
    item_id = uuid4()
    with Session(eng) as db:
        db.add(Lab(id=lab_id, name="Orphan Lab", created_at=now, updated_at=now))
        db.add(
            InventoryItem(
                id=item_id,
                ic_no="IRD/MIG/ORPHAN",
                item_name="Orphan assignee",
                assigned_to="Gone",
                assigned_scholar_id=ghost,
                assigned_at=now,
                assign_verify_method="document",
                status="active",
                created_at=now,
                updated_at=now,
            )
        )
        db.commit()

    with eng.begin() as conn:
        ensure_inventory_assignments_table(conn)  # must not raise

    with eng.connect() as conn:
        n = conn.execute(text("SELECT COUNT(*) FROM inventory_assignments")).scalar_one()
    assert n == 0


def test_ensure_backfill_strips_tzinfo_from_aware_assigned_at():
    """asyncpg TIMESTAMP rejects aware datetimes — must strip tz before bind."""
    eng = _engine()
    aware = datetime(2026, 11, 16, 6, 25, 17, 893079, tzinfo=timezone.utc)
    lab_id = uuid4()
    scholar_id = uuid4()
    item_id = uuid4()
    with Session(eng) as db:
        db.add(Lab(id=lab_id, name="TZ Lab", created_at=aware, updated_at=aware))
        db.add(
            Scholar(
                id=scholar_id,
                lab_id=lab_id,
                full_name="TZ Scholar",
                scholar_id="TZ-1",
                created_at=aware,
                updated_at=aware,
            )
        )
        db.add(
            InventoryItem(
                id=item_id,
                ic_no="IRD/MIG/TZ",
                item_name="Aware assigned_at",
                assigned_to="TZ Scholar",
                assigned_scholar_id=scholar_id,
                assigned_at=aware,
                assign_verify_method="document",
                status="active",
                created_at=aware,
                updated_at=aware,
            )
        )
        db.commit()

    with eng.begin() as conn:
        ensure_inventory_assignments_table(conn)

    with eng.connect() as conn:
        row = conn.execute(
            text(
                "SELECT assigned_at, created_at, updated_at FROM inventory_assignments "
                "WHERE inventory_item_id = :iid"
            ),
            {"iid": item_id.hex},
        ).fetchone()
    assert row is not None
    for val in row:
        assert val is not None
        assert getattr(val, "tzinfo", None) in (None,)


def test_ensure_is_idempotent():
    eng = _engine()
    now = datetime.now(timezone.utc)
    lab_id = uuid4()
    scholar_id = uuid4()
    item_id = uuid4()
    with Session(eng) as db:
        db.add(Lab(id=lab_id, name="Idem Lab", created_at=now, updated_at=now))
        db.add(
            Scholar(
                id=scholar_id,
                lab_id=lab_id,
                full_name="Idem",
                scholar_id="IDEM-1",
                created_at=now,
                updated_at=now,
            )
        )
        db.add(
            InventoryItem(
                id=item_id,
                ic_no="IRD/MIG/IDEM",
                item_name="Idem",
                assigned_scholar_id=scholar_id,
                assigned_at=now,
                assign_verify_method="otp",
                status="active",
                created_at=now,
                updated_at=now,
            )
        )
        db.commit()

    with eng.begin() as conn:
        ensure_inventory_assignments_table(conn)
    with eng.begin() as conn:
        ensure_inventory_assignments_table(conn)

    with eng.connect() as conn:
        n = conn.execute(text("SELECT COUNT(*) FROM inventory_assignments")).scalar_one()
    assert n == 1
