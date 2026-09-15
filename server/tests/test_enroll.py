import gzip

import pytest
from httpx import AsyncClient

from app.config import get_settings
from app.services.public_url import hostname_server_url, normalize_inventory_id


def test_inventory_id_format():
    assert normalize_inventory_id("12345/2012/12") == "12345/2012/12"
    with pytest.raises(Exception):
        normalize_inventory_id("just-a-name")
    with pytest.raises(Exception):
        normalize_inventory_id("")


def test_hostname_server_url_ignores_lan_ip(monkeypatch):
    monkeypatch.setenv("LABWATCH_PUBLIC_URL", "http://10.10.1.5")
    get_settings.cache_clear()
    assert hostname_server_url() == "http://hobbit2.cse.iitd.ac.in"
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_enroll_mints_token_and_register_sets_inventory_id(client: AsyncClient):
    denied = await client.post(
        "/api/agents/enroll",
        json={"username": "admin", "password": "wrong", "inventory_id": "12345/2012/12"},
    )
    assert denied.status_code == 401

    enrolled = await client.post(
        "/api/agents/enroll",
        json={"username": "admin", "password": "testpass123", "inventory_id": "12345/2012/12", "lab": "Unassigned"},
    )
    assert enrolled.status_code == 200, enrolled.text
    body = enrolled.json()
    assert body["inventory_id"] == "12345/2012/12"
    assert "hobbit2.cse.iitd.ac.in" in body["server_url"]
    token = body["registration_token"]
    assert token.startswith("lw_")

    reg = await client.post(
        "/api/agents/register",
        json={
            "registration_token": token,
            "inventory_id": "12345/2012/12",
            "agent_uuid": "agent-inv-001",
            "agent_version": "1.0.0",
            "identity": {
                "hostname": "gpu-lab-01",
                "os_name": "Linux",
                "architecture": "x86_64",
                "system_uuid": "sys-inv-001",
            },
        },
    )
    assert reg.status_code == 200, reg.text
    machine_id = reg.json()["machine_id"]
    login = await client.post("/api/auth/login", json={"username": "admin", "password": "testpass123"})
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    listed = await client.get("/api/machines", headers=headers)
    row = next(m for m in listed.json() if m["id"] == machine_id)
    assert row["inventory_id"] == "12345/2012/12"
    assert row["display_name"] == "12345/2012/12"


@pytest.mark.asyncio
async def test_viewer_cannot_enroll(client: AsyncClient, auth_headers):
    created = await client.post(
        "/api/admin/users",
        headers=auth_headers,
        json={"username": "viewenroll", "email": "viewenroll@example.com", "password": "viewerpass", "role": "VIEWER"},
    )
    assert created.status_code == 200
    denied = await client.post(
        "/api/agents/enroll",
        json={"username": "viewenroll", "password": "viewerpass", "inventory_id": "999/1/1"},
    )
    assert denied.status_code == 403


@pytest.mark.asyncio
async def test_install_script_and_agent_pack(client: AsyncClient):
    script = await client.get("/install-agent.sh")
    assert script.status_code == 200, script.text
    text = script.text
    assert "hobbit2.cse.iitd.ac.in" in text
    assert "__SERVER_URL__" not in text
    assert "/api/agents/enroll" in text
    assert "Machine ID" in text

    pack = await client.get("/agent-pack.tgz")
    assert pack.status_code == 200
    assert pack.content[:2] == b"\x1f\x8b"
    gzip.decompress(pack.content)
