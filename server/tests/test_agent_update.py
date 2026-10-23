"""Server-pushed agent self-update queue + heartbeat delivery + ack."""

from httpx import AsyncClient


async def _register_agent(client: AsyncClient, auth_headers: dict, hostname: str = "upd-host"):
    enroll = await client.post(
        "/api/agents/enroll",
        headers=auth_headers,
        json={"username": "admin", "password": "testpass123", "inventory_id": f"INV/{hostname}"},
    )
    assert enroll.status_code == 200, enroll.text
    token = enroll.json()["registration_token"]
    reg = await client.post(
        "/api/agents/register",
        json={
            "registration_token": token,
            "agent_uuid": f"agent-uuid-{hostname}",
            "agent_version": "1.1.43",
            "inventory_id": f"INV/{hostname}",
            "identity": {
                "hostname": hostname,
                "os_name": "Linux",
                "architecture": "x86_64",
                "ip_addresses": ["10.0.0.9"],
                "mac_addresses": ["aa:bb:cc:dd:ee:09"],
                "is_virtual": False,
            },
        },
    )
    assert reg.status_code == 200, reg.text
    data = reg.json()
    return {
        "headers": {"Authorization": f"Bearer {data['agent_id']}:{data['agent_secret']}"},
        "agent_id": data["agent_id"],
        "machine_id": data["machine_id"],
    }


async def test_queue_update_delivered_on_heartbeat(client: AsyncClient, auth_headers: dict):
    enrolled = await _register_agent(client, auth_headers, "upd-a")
    agents = await client.get("/api/admin/agents", headers=auth_headers)
    assert agents.status_code == 200
    payload = agents.json()
    assert payload["current_version"]
    row = next(a for a in payload["agents"] if a["agent_id"] == enrolled["agent_id"])
    assert row["inventory_id"] == "INV/upd-a"
    assert row["remote_update_capable"] is True
    assert row["up_to_date"] is True
    assert row["update_available"] is False
    assert row["current_version"] == payload["current_version"]

    q = await client.post(
        "/api/admin/agents/update",
        headers=auth_headers,
        json={"agent_ids": [row["id"]]},
    )
    assert q.status_code == 200, q.text
    assert q.json()["queued"] == [row["id"]]
    assert q.json()["target_version"]

    hb = await client.post(
        "/api/agents/heartbeat",
        headers=enrolled["headers"],
        json={"agent_version": "1.1.43", "hostname": "upd-a", "status": "healthy"},
    )
    assert hb.status_code == 200, hb.text
    body = hb.json()
    assert len(body["commands"]) == 1
    cmd = body["commands"][0]
    assert cmd["type"] == "self_update"
    assert cmd["pack_path"] == "/agent-pack.tgz"
    assert cmd["id"]

    # Second heartbeat should not re-deliver while still "sent"
    hb2 = await client.post(
        "/api/agents/heartbeat",
        headers=enrolled["headers"],
        json={"agent_version": "1.1.43", "hostname": "upd-a", "status": "healthy"},
    )
    assert hb2.json()["commands"] == []

    ack = await client.post(
        "/api/agents/commands/ack",
        headers=enrolled["headers"],
        json={"id": cmd["id"], "status": "ok", "message": "updated to 1.1.43", "agent_version": "1.1.43"},
    )
    assert ack.status_code == 200
    assert ack.json()["ignored"] is False

    agents2 = await client.get("/api/admin/agents", headers=auth_headers)
    row2 = next(a for a in agents2.json()["agents"] if a["id"] == row["id"])
    assert row2["update_status"] == "ok"
    assert row2["version"] == "1.1.43"


async def test_update_requires_selection(client: AsyncClient, auth_headers: dict):
    r = await client.post("/api/admin/agents/update", headers=auth_headers, json={"agent_ids": []})
    assert r.status_code == 400


async def test_update_selected_only(client: AsyncClient, auth_headers: dict):
    a = await _register_agent(client, auth_headers, "upd-b1")
    b = await _register_agent(client, auth_headers, "upd-b2")
    agents = (await client.get("/api/admin/agents", headers=auth_headers)).json()["agents"]
    id_a = next(x["id"] for x in agents if x["agent_id"] == a["agent_id"])
    id_b = next(x["id"] for x in agents if x["agent_id"] == b["agent_id"])

    q = await client.post(
        "/api/admin/agents/update",
        headers=auth_headers,
        json={"agent_ids": [id_a]},
    )
    assert q.status_code == 200
    assert q.json()["queued"] == [id_a]

    hb_a = await client.post(
        "/api/agents/heartbeat",
        headers=a["headers"],
        json={"agent_version": "1.1.43", "hostname": "upd-b1", "status": "healthy"},
    )
    hb_b = await client.post(
        "/api/agents/heartbeat",
        headers=b["headers"],
        json={"agent_version": "1.1.43", "hostname": "upd-b2", "status": "healthy"},
    )
    assert len(hb_a.json()["commands"]) == 1
    assert hb_b.json()["commands"] == []
    assert id_b  # registered
