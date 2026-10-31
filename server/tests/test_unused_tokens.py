"""Unused registration tokens auto-revoke + delete after N days."""

from datetime import timedelta
from uuid import UUID

import pytest
from httpx import AsyncClient

from app.db import get_session_factory
from app.models import RegistrationToken, utcnow
from app.services.retention import prune_unused_registration_tokens


@pytest.mark.asyncio
async def test_unused_tokens_pruned_after_two_days(client: AsyncClient, auth_headers: dict):
    created = await client.post(
        "/api/admin/tokens",
        headers=auth_headers,
        json={"label": "stale-unused", "expires_hours": 168},
    )
    assert created.status_code == 200, created.text
    token_id = created.json()["id"]

    kept = await client.post(
        "/api/admin/tokens",
        headers=auth_headers,
        json={"label": "fresh-unused", "expires_hours": 168},
    )
    assert kept.status_code == 200
    kept_id = kept.json()["id"]

    used = await client.post(
        "/api/admin/tokens",
        headers=auth_headers,
        json={"label": "old-but-used", "expires_hours": 168, "max_uses": 5},
    )
    assert used.status_code == 200
    used_id = used.json()["id"]

    factory = get_session_factory()
    async with factory() as db:
        stale = await db.get(RegistrationToken, UUID(token_id))
        assert stale is not None
        stale.created_at = utcnow() - timedelta(days=3)

        used_row = await db.get(RegistrationToken, UUID(used_id))
        assert used_row is not None
        used_row.created_at = utcnow() - timedelta(days=10)
        used_row.use_count = 1
        await db.commit()

    async with factory() as db:
        deleted = await prune_unused_registration_tokens(db)
        await db.commit()
        assert deleted >= 1

        gone = await db.get(RegistrationToken, UUID(token_id))
        assert gone is None

        still_fresh = await db.get(RegistrationToken, UUID(kept_id))
        assert still_fresh is not None
        assert still_fresh.use_count == 0

        still_used = await db.get(RegistrationToken, UUID(used_id))
        assert still_used is not None
        assert still_used.use_count == 1

    listed = await client.get("/api/admin/tokens", headers=auth_headers)
    assert listed.status_code == 200
    ids = {t["id"] for t in listed.json()}
    assert token_id not in ids
    assert kept_id in ids
    assert used_id in ids
    by_id = {t["id"]: t for t in listed.json()}
    assert by_id[kept_id]["status"] == "unused"
    assert by_id[kept_id]["last_used_at"] is None
    assert by_id[used_id]["status"] == "used"
    assert by_id[used_id]["use_count"] == 1
    assert listed.json()[0]["unused_auto_delete_days"] == 2


@pytest.mark.asyncio
async def test_token_last_used_set_on_register(client: AsyncClient, auth_headers: dict):
    created = await client.post(
        "/api/admin/tokens",
        headers=auth_headers,
        json={"label": "use-me", "expires_hours": 24, "max_uses": 3},
    )
    assert created.status_code == 200
    raw = created.json()["token"]
    tid = created.json()["id"]

    reg = await client.post(
        "/api/agents/register",
        json={
            "registration_token": raw,
            "agent_uuid": "agent-uuid-token-use",
            "agent_version": "1.1.50",
            "inventory_id": "INV/token-use",
            "identity": {
                "hostname": "token-use-host",
                "os_name": "Linux",
                "architecture": "x86_64",
                "ip_addresses": ["10.0.0.44"],
                "mac_addresses": ["aa:bb:cc:dd:ee:44"],
                "is_virtual": False,
            },
        },
    )
    assert reg.status_code == 200, reg.text

    listed = await client.get("/api/admin/tokens", headers=auth_headers)
    row = next(t for t in listed.json() if t["id"] == tid)
    assert row["status"] == "used"
    assert row["use_count"] == 1
    assert row["last_used_at"]
    assert row["enrolled_agents"] >= 1
