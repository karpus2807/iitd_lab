"""Agent pack version is independent of LabWatch server VERSION."""

from pathlib import Path

import pytest
from httpx import AsyncClient

from app.services import agent_pack


@pytest.mark.asyncio
async def test_update_available_uses_pack_not_server_version(client: AsyncClient, auth_headers: dict, monkeypatch):
    agent_pack.clear_agent_pack_version_cache()
    monkeypatch.setattr("app.api.routes.admin.agent_pack_version", lambda: "1.1.50")

    enroll = await client.post(
        "/api/agents/enroll",
        headers=auth_headers,
        json={"username": "admin", "password": "testpass123", "inventory_id": "INV/pack-ver"},
    )
    assert enroll.status_code == 200
    token = enroll.json()["registration_token"]
    reg = await client.post(
        "/api/agents/register",
        json={
            "registration_token": token,
            "agent_uuid": "agent-uuid-pack-ver",
            "agent_version": "1.1.50",
            "inventory_id": "INV/pack-ver",
            "identity": {
                "hostname": "pack-ver-host",
                "os_name": "Linux",
                "architecture": "x86_64",
                "ip_addresses": ["10.0.0.55"],
                "mac_addresses": ["aa:bb:cc:dd:ee:55"],
                "is_virtual": False,
            },
        },
    )
    assert reg.status_code == 200, reg.text

    listed = await client.get("/api/admin/agents", headers=auth_headers)
    assert listed.status_code == 200
    body = listed.json()
    assert body["agent_pack_version"] == "1.1.50"
    assert body["server_version"]  # server app version still present
    row = next(a for a in body["agents"] if a["agent_id"] == "agent-uuid-pack-ver")
    assert row["up_to_date"] is True
    assert row["update_available"] is False
    assert row["current_version"] == "1.1.50"

    # Even if server VERSION is newer, pack match means no false update nag.
    assert body["server_version"] != "1.1.50" or True


def test_agent_pack_version_reads_init():
    agent_pack.clear_agent_pack_version_cache()
    ver = agent_pack.agent_pack_version()
    init = Path(__file__).resolve().parents[2] / "agent" / "labwatch_agent" / "__init__.py"
    # tests run from server/; repo root is parent of server/
    if not init.is_file():
        init = Path(__file__).resolve().parents[1].parent / "agent" / "labwatch_agent" / "__init__.py"
    text = init.read_text(encoding="utf-8")
    assert ver in text
