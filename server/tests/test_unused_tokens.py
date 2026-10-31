"""Registration token monitoring: last-used, supersede revoke, manual delete."""

from uuid import UUID

import pytest
from httpx import AsyncClient

from app.db import get_session_factory
from app.models import RegistrationToken
from app.services.retention import prune_unused_registration_tokens


@pytest.mark.asyncio
async def test_time_based_token_prune_disabled_by_default(client: AsyncClient, auth_headers: dict):
    created = await client.post(
        "/api/admin/tokens",
        headers=auth_headers,
        json={"label": "keep-forever-unused", "expires_hours": 168},
    )
    assert created.status_code == 200, created.text
    token_id = created.json()["id"]

    factory = get_session_factory()
    async with factory() as db:
        deleted = await prune_unused_registration_tokens(db)
        await db.commit()
        assert deleted == 0
        still = await db.get(RegistrationToken, UUID(token_id))
        assert still is not None

    listed = await client.get("/api/admin/tokens", headers=auth_headers)
    assert listed.status_code == 200
    assert any(t["id"] == token_id for t in listed.json())


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
    assert any(a["hostname"] == "token-use-host" for a in row["agents"])


@pytest.mark.asyncio
async def test_heartbeat_updates_token_last_used(client: AsyncClient, auth_headers: dict):
    created = await client.post(
        "/api/admin/tokens",
        headers=auth_headers,
        json={"label": "hb-token", "expires_hours": 24},
    )
    raw = created.json()["token"]
    tid = created.json()["id"]
    reg = await client.post(
        "/api/agents/register",
        json={
            "registration_token": raw,
            "agent_uuid": "agent-uuid-hb-token",
            "agent_version": "1.1.50",
            "inventory_id": "INV/hb-token",
            "identity": {
                "hostname": "hb-token-host",
                "os_name": "Linux",
                "architecture": "x86_64",
                "ip_addresses": ["10.0.0.55"],
                "mac_addresses": ["aa:bb:cc:dd:ee:55"],
                "is_virtual": False,
            },
        },
    )
    assert reg.status_code == 200, reg.text
    secret = reg.json()["agent_secret"]
    agent_id = reg.json()["agent_id"]
    agent_headers = {"Authorization": f"Bearer {agent_id}:{secret}"}

    # Clear stored last_used so heartbeat must refresh it (list also falls back to HB time).
    factory = get_session_factory()
    async with factory() as db:
        row = await db.get(RegistrationToken, UUID(tid))
        assert row is not None
        row.last_used_at = None
        await db.commit()

    hb = await client.post(
        "/api/agents/heartbeat",
        headers=agent_headers,
        json={
            "agent_version": "1.1.50",
            "status": "healthy",
            "hostname": "hb-token-host",
            "ip_addresses": ["10.0.0.55"],
        },
    )
    assert hb.status_code == 200, hb.text

    listed2 = await client.get("/api/admin/tokens", headers=auth_headers)
    t1 = next(t for t in listed2.json() if t["id"] == tid)
    assert t1["last_used_at"]
    assert any(a["hostname"] == "hb-token-host" for a in t1["agents"])


@pytest.mark.asyncio
async def test_reregister_with_new_token_revokes_previous_when_unused(
    client: AsyncClient, auth_headers: dict
):
    t1 = await client.post(
        "/api/admin/tokens",
        headers=auth_headers,
        json={"label": "old-tok", "expires_hours": 24},
    )
    t2 = await client.post(
        "/api/admin/tokens",
        headers=auth_headers,
        json={"label": "new-tok", "expires_hours": 24},
    )
    old_raw, old_id = t1.json()["token"], t1.json()["id"]
    new_raw, new_id = t2.json()["token"], t2.json()["id"]

    identity = {
        "hostname": "supersede-host",
        "os_name": "Linux",
        "architecture": "x86_64",
        "system_uuid": "sys-supersede-1",
        "machine_uuid": "mach-supersede-1",
        "ip_addresses": ["10.0.0.66"],
        "mac_addresses": ["aa:bb:cc:dd:ee:66"],
        "is_virtual": False,
    }
    r1 = await client.post(
        "/api/agents/register",
        json={
            "registration_token": old_raw,
            "agent_uuid": "agent-supersede-1",
            "agent_version": "1.1.50",
            "inventory_id": "INV/supersede",
            "identity": identity,
        },
    )
    assert r1.status_code == 200, r1.text

    r2 = await client.post(
        "/api/agents/register",
        json={
            "registration_token": new_raw,
            "agent_uuid": "agent-supersede-1",
            "agent_version": "1.1.50",
            "inventory_id": "INV/supersede",
            "identity": identity,
        },
    )
    assert r2.status_code == 200, r2.text

    listed = await client.get("/api/admin/tokens", headers=auth_headers)
    by_id = {t["id"]: t for t in listed.json()}
    assert by_id[old_id]["revoked"] is True
    assert by_id[old_id]["status"] == "revoked"
    assert by_id[new_id]["status"] == "used"
    assert by_id[new_id]["enrolled_agents"] == 1

    agents = await client.get("/api/admin/agents", headers=auth_headers)
    body = agents.json()
    rows = body if isinstance(body, list) else body.get("agents", [])
    mine = next(a for a in rows if a.get("inventory_id") == "INV/supersede")
    assert mine["registration_token_id"] == new_id
    assert mine["token_prefix"]


@pytest.mark.asyncio
async def test_shared_token_not_revoked_when_one_machine_moves(
    client: AsyncClient, auth_headers: dict
):
    shared = await client.post(
        "/api/admin/tokens",
        headers=auth_headers,
        json={"label": "shared-lab", "expires_hours": 24},
    )
    other = await client.post(
        "/api/admin/tokens",
        headers=auth_headers,
        json={"label": "solo-new", "expires_hours": 24},
    )
    shared_raw, shared_id = shared.json()["token"], shared.json()["id"]
    other_raw = other.json()["token"]

    for i, host in enumerate(("share-a", "share-b")):
        r = await client.post(
            "/api/agents/register",
            json={
                "registration_token": shared_raw,
                "agent_uuid": f"agent-share-{i}",
                "agent_version": "1.1.50",
                "inventory_id": f"INV/share-{i}",
                "identity": {
                    "hostname": host,
                    "os_name": "Linux",
                    "architecture": "x86_64",
                    "system_uuid": f"sys-share-{i}",
                    "machine_uuid": f"mach-share-{i}",
                    "ip_addresses": [f"10.0.1.{i}"],
                    "mac_addresses": [f"aa:bb:cc:dd:01:0{i}"],
                    "is_virtual": False,
                },
            },
        )
        assert r.status_code == 200, r.text

    # Move only share-a to a new token.
    move = await client.post(
        "/api/agents/register",
        json={
            "registration_token": other_raw,
            "agent_uuid": "agent-share-0",
            "agent_version": "1.1.50",
            "inventory_id": "INV/share-0",
            "identity": {
                "hostname": "share-a",
                "os_name": "Linux",
                "architecture": "x86_64",
                "system_uuid": "sys-share-0",
                "machine_uuid": "mach-share-0",
                "ip_addresses": ["10.0.1.0"],
                "mac_addresses": ["aa:bb:cc:dd:01:00"],
                "is_virtual": False,
            },
        },
    )
    assert move.status_code == 200, move.text

    listed = await client.get("/api/admin/tokens", headers=auth_headers)
    shared_row = next(t for t in listed.json() if t["id"] == shared_id)
    assert shared_row["revoked"] is False
    assert shared_row["enrolled_agents"] == 1  # share-b still on it


@pytest.mark.asyncio
async def test_manual_revoke_and_delete_token(client: AsyncClient, auth_headers: dict):
    created = await client.post(
        "/api/admin/tokens",
        headers=auth_headers,
        json={"label": "to-delete", "expires_hours": 24},
    )
    tid = created.json()["id"]

    rev = await client.post(f"/api/admin/tokens/{tid}/revoke", headers=auth_headers)
    assert rev.status_code == 200

    deleted = await client.delete(f"/api/admin/tokens/{tid}", headers=auth_headers)
    assert deleted.status_code == 200, deleted.text

    listed = await client.get("/api/admin/tokens", headers=auth_headers)
    assert tid not in {t["id"] for t in listed.json()}
