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
    assert "/api/labs" in text
    assert "Select lab number" in text
    assert "lab_id" in text
    assert "Enter keeps" in text
    assert "inventory_id=" in text
    assert "/api/machines?inventory_id=" in text
    assert "dmidecode" in text
    assert "pciutils" in text

    pack = await client.get("/agent-pack.tgz")
    assert pack.status_code == 200
    assert pack.content[:2] == b"\x1f\x8b"
    gzip.decompress(pack.content)


def _identity(suffix: str) -> dict:
    return {
        "hostname": f"host-{suffix}",
        "os_name": "Linux",
        "architecture": "x86_64",
        "system_uuid": f"sys-{suffix}",
    }


@pytest.mark.asyncio
async def test_enroll_with_lab_id_and_gui_reassign(client: AsyncClient, auth_headers):
    created = await client.post("/api/labs", headers=auth_headers, json={"name": "GPU Lab Select"})
    assert created.status_code == 200, created.text
    lab_id = created.json()["id"]

    bad = await client.post(
        "/api/agents/enroll",
        json={
            "username": "admin",
            "password": "testpass123",
            "inventory_id": "55555/2012/12",
            "lab_id": "00000000-0000-0000-0000-000000000001",
        },
    )
    assert bad.status_code == 400

    enrolled = await client.post(
        "/api/agents/enroll",
        json={
            "username": "admin",
            "password": "testpass123",
            "inventory_id": "55555/2012/12",
            "lab_id": lab_id,
        },
    )
    assert enrolled.status_code == 200, enrolled.text
    token = enrolled.json()["registration_token"]
    assert enrolled.json()["lab"] == "GPU Lab Select"

    reg = await client.post(
        "/api/agents/register",
        json={
            "registration_token": token,
            "inventory_id": "55555/2012/12",
            "agent_uuid": "agent-lab-001",
            "agent_version": "1.0.0",
            "identity": _identity("lab-001"),
        },
    )
    assert reg.status_code == 200, reg.text
    machine_id = reg.json()["machine_id"]
    listed = await client.get("/api/machines", headers=auth_headers)
    row = next(m for m in listed.json() if m["id"] == machine_id)
    assert row["lab_name"] == "GPU Lab Select"
    assert row["lab_id"] == lab_id

    labs = (await client.get("/api/labs", headers=auth_headers)).json()
    unassigned = next(x for x in labs if x["name"] == "Unassigned")
    moved = await client.patch(
        f"/api/machines/{machine_id}",
        headers=auth_headers,
        json={"lab_id": unassigned["id"]},
    )
    assert moved.status_code == 200, moved.text
    after = await client.get(f"/api/machines/{machine_id}", headers=auth_headers)
    assert after.json()["lab_name"] == "Unassigned"

    back = await client.patch(
        f"/api/machines/{machine_id}",
        headers=auth_headers,
        json={"lab_id": lab_id},
    )
    assert back.status_code == 200
    restored = await client.get(f"/api/machines/{machine_id}", headers=auth_headers)
    assert restored.json()["lab_name"] == "GPU Lab Select"


@pytest.mark.asyncio
async def test_reinstall_without_lab_keeps_lab_and_delete_removes_host(client: AsyncClient, auth_headers):
    created = await client.post("/api/labs", headers=auth_headers, json={"name": "Keep Lab"})
    assert created.status_code == 200, created.text
    lab_id = created.json()["id"]
    enrolled = await client.post(
        "/api/agents/enroll",
        json={
            "username": "admin",
            "password": "testpass123",
            "inventory_id": "77777/2012/12",
            "lab_id": lab_id,
        },
    )
    assert enrolled.status_code == 200, enrolled.text
    reg = await client.post(
        "/api/agents/register",
        json={
            "registration_token": enrolled.json()["registration_token"],
            "inventory_id": "77777/2012/12",
            "agent_uuid": "agent-keep-001",
            "agent_version": "1.1.15",
            "identity": _identity("keep-001"),
        },
    )
    assert reg.status_code == 200, reg.text
    machine_id = reg.json()["machine_id"]

    found = await client.get("/api/machines?inventory_id=77777/2012/12", headers=auth_headers)
    assert found.status_code == 200
    assert found.json()[0]["id"] == machine_id
    assert found.json()[0]["lab_name"] == "Keep Lab"

    again = await client.post(
        "/api/agents/enroll",
        json={"username": "admin", "password": "testpass123", "inventory_id": "77777/2012/12"},
    )
    assert again.status_code == 200, again.text
    assert again.json()["lab"] == "Unassigned"
    rereg = await client.post(
        "/api/agents/register",
        json={
            "registration_token": again.json()["registration_token"],
            "inventory_id": "77777/2012/12",
            "agent_uuid": "agent-keep-002",
            "agent_version": "1.1.15",
            "identity": _identity("keep-001"),
        },
    )
    assert rereg.status_code == 200, rereg.text
    assert rereg.json()["machine_id"] == machine_id
    kept = await client.get(f"/api/machines/{machine_id}", headers=auth_headers)
    assert kept.json()["lab_name"] == "Keep Lab"

    viewer = await client.post(
        "/api/admin/users",
        headers=auth_headers,
        json={"username": "viewdel", "email": "viewdel@example.com", "password": "viewerpass", "role": "VIEWER"},
    )
    assert viewer.status_code == 200
    login = await client.post("/api/auth/login", json={"username": "viewdel", "password": "viewerpass"})
    denied = await client.delete(
        f"/api/machines/{machine_id}",
        headers={"Authorization": f"Bearer {login.json()['access_token']}"},
    )
    assert denied.status_code == 403

    removed = await client.delete(f"/api/machines/{machine_id}", headers=auth_headers)
    assert removed.status_code == 200, removed.text
    missing = await client.get(f"/api/machines/{machine_id}", headers=auth_headers)
    assert missing.status_code == 404
    listed = await client.get("/api/machines", headers=auth_headers)
    assert all(row["id"] != machine_id for row in listed.json())
