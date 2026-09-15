import pytest
from httpx import AsyncClient

from app.schemas.inventory import GPUInfo, InventoryPayload, MemoryInfo, MemoryModule


@pytest.mark.asyncio
async def test_health(client: AsyncClient):
    r = await client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_login_and_me(client: AsyncClient):
    bad = await client.post("/api/auth/login", json={"username": "admin", "password": "wrong"})
    assert bad.status_code == 401
    ok = await client.post("/api/auth/login", json={"username": "admin", "password": "testpass123"})
    assert ok.status_code == 200
    token = ok.json()["access_token"]
    me = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["role"] == "ADMIN"


@pytest.mark.asyncio
async def test_viewer_cannot_create_lab(client: AsyncClient, auth_headers):
    created = await client.post(
        "/api/admin/users",
        headers=auth_headers,
                json={"username": "viewer1", "email": "viewer@example.com", "password": "viewerpass", "role": "VIEWER"},
    )
    assert created.status_code == 200
    login = await client.post("/api/auth/login", json={"username": "viewer1", "password": "viewerpass"})
    token = login.json()["access_token"]
    denied = await client.post("/api/labs", headers={"Authorization": f"Bearer {token}"}, json={"name": "X"})
    assert denied.status_code == 403


@pytest.mark.asyncio
async def test_agent_register_heartbeat_inventory_offline(client: AsyncClient, auth_headers):
    tok = await client.post("/api/admin/tokens", headers=auth_headers, json={"label": "lab", "expires_hours": 24})
    assert tok.status_code == 200
    registration = tok.json()["token"]
    labs = await client.get("/api/labs", headers=auth_headers)
    dair = next(x for x in labs.json() if x["name"] == "DAIR LAB")

    reg = await client.post(
        "/api/agents/register",
        json={
            "registration_token": registration,
            "agent_uuid": "agent-stable-001",
            "agent_version": "1.0.0",
            "identity": {
                "hostname": "LAB-PC-042",
                "os_name": "Linux",
                "os_version": "Ubuntu 24.04",
                "architecture": "x86_64",
                "system_uuid": "sys-uuid-042",
                "machine_uuid": "mach-uuid-042",
                "mac_addresses": ["aa:bb:cc:dd:ee:01"],
                "is_virtual": False,
            },
        },
    )
    assert reg.status_code == 200, reg.text
    creds = reg.json()
    agent_headers = {"Authorization": f"Bearer {creds['agent_id']}:{creds['agent_secret']}"}

    hb = await client.post(
        "/api/agents/heartbeat",
        headers=agent_headers,
        json={"agent_version": "1.0.0", "hostname": "LAB-PC-042", "ip_addresses": ["10.0.1.42"], "status": "healthy"},
    )
    assert hb.status_code == 200, hb.text
    assert hb.json()["status"] == "ONLINE"

    inv1 = InventoryPayload(
        identity={"hostname": "LAB-PC-042", "os_name": "Linux", "architecture": "x86_64", "system_uuid": "sys-uuid-042"},
        cpu={"manufacturer": "Intel", "model": "Xeon", "physical_cores": 8, "logical_processors": 16},
        memory=MemoryInfo(
            total_physical_bytes=48 * 1024**3,
            max_supported_bytes=128 * 1024**3,
            slot_count=4,
            occupied_slots=3,
            free_slots=1,
            topology_status="DETECTED",
            modules=[
                MemoryModule(slot_locator="A1", occupied=True, capacity_bytes=16 * 1024**3, manufacturer="Samsung", speed_mts=3200, serial_number="S1"),
                MemoryModule(slot_locator="A2", occupied=True, capacity_bytes=16 * 1024**3, manufacturer="Samsung", speed_mts=3200, serial_number="S2"),
                MemoryModule(slot_locator="B1", occupied=True, capacity_bytes=16 * 1024**3, manufacturer="Samsung", speed_mts=3200, serial_number="S3"),
                MemoryModule(slot_locator="B2", occupied=False),
            ],
        ),
        gpus=[
            GPUInfo(index=0, vendor="NVIDIA", model="RTX 4090", pci_bus="0000:01:00.0", vram_bytes=24 * 1024**3, slot_designation="Slot 1"),
            GPUInfo(index=1, vendor="NVIDIA", model="RTX 3090", pci_bus="0000:02:00.0", vram_bytes=24 * 1024**3, slot_designation="Slot 2"),
        ],
        storage={"disks": [{"name": "nvme0n1", "model": "Samsung 980", "serial_number": "NV1", "capacity_bytes": 10**12, "media_type": "NVMe"}]},
    )
    r = await client.post("/api/agents/inventory", headers=agent_headers, json=inv1.model_dump(mode="json"))
    assert r.status_code == 200, r.text

    inv2 = inv1.model_copy(deep=True)
    inv2.memory.modules[2].occupied = False
    inv2.memory.modules[2].capacity_bytes = None
    inv2.memory.occupied_slots = 2
    inv2.memory.free_slots = 2
    inv2.gpus = [inv1.gpus[0]]
    r = await client.post("/api/agents/inventory", headers=agent_headers, json=inv2.model_dump(mode="json"))
    assert r.status_code == 200
    assert r.json()["events"] >= 2

    machines = await client.get("/api/machines", headers=auth_headers)
    machine = next(m for m in machines.json() if m["hostname"] == "LAB-PC-042")
    hw = await client.get(f"/api/machines/{machine['id']}/hardware", headers=auth_headers)
    assert hw.status_code == 200
    body = hw.json()
    assert body["memory"]["slot_count"] == 4
    assert body["memory"]["occupied_slots"] == 2
    assert body["memory"]["free_slots"] == 2
    assert len(body["gpus"]) == 1

    events = await client.get(f"/api/machines/{machine['id']}/events", headers=auth_headers)
    types = {e["event_type"] for e in events.json()}
    assert "RAM_REMOVED" in types
    assert "GPU_REMOVED" in types

    metrics = await client.post(
        "/api/agents/metrics",
        headers=agent_headers,
        json={
            "cpu_usage_pct": 12.5,
            "cpu_temp_c": 48,
            "ram_usage_pct": 22.0,
            "ram_used_bytes": 10 * 1024**3,
            "ram_total_bytes": 48 * 1024**3,
            "gpus": [{"index": 0, "utilization_pct": 70, "temperature_c": 57, "vram_used_bytes": 18 * 1024**3, "vram_total_bytes": 24 * 1024**3}],
        },
    )
    assert metrics.status_code == 200

    dash = await client.get("/api/dashboard/summary", headers=auth_headers)
    assert dash.status_code == 200
    assert dash.json()["machines"] >= 1
    assert dash.json()["online"] >= 1

    # Re-register with same hardware identity after DHCP IP change must map to same machine.
    reg2 = await client.post(
        "/api/agents/register",
        json={
            "registration_token": registration,
            "agent_uuid": "agent-stable-001",
            "agent_version": "1.0.1",
            "identity": {
                "hostname": "LAB-PC-042",
                "os_name": "Linux",
                "architecture": "x86_64",
                "system_uuid": "sys-uuid-042",
                "machine_uuid": "mach-uuid-042",
            },
        },
    )
    assert reg2.status_code == 200
    machines2 = await client.get("/api/machines", headers=auth_headers)
    ids = [m["id"] for m in machines2.json() if m["hostname"] == "LAB-PC-042"]
    assert len(ids) == 1


@pytest.mark.asyncio
async def test_lan_switch_updates_ip_same_machine(client: AsyncClient, auth_headers):
    tok = await client.post("/api/admin/tokens", headers=auth_headers, json={"label": "lan", "expires_hours": 24})
    registration = tok.json()["token"]
    reg = await client.post(
        "/api/agents/register",
        json={
            "registration_token": registration,
            "agent_uuid": "agent-lan-switch-001",
            "identity": {
                "hostname": "LAB-PC-077",
                "os_name": "Linux",
                "architecture": "x86_64",
                "system_uuid": "sys-uuid-077",
                "machine_uuid": "mach-uuid-077",
            },
        },
    )
    assert reg.status_code == 200
    secret = reg.json()["agent_secret"]
    headers = {"Authorization": f"Bearer agent-lan-switch-001:{secret}"}
    first = await client.post(
        "/api/agents/heartbeat",
        headers=headers,
        json={"hostname": "LAB-PC-077", "ip_addresses": ["192.168.1.77", "127.0.0.1"], "status": "healthy"},
    )
    assert first.status_code == 200
    machines = await client.get("/api/machines", headers=auth_headers)
    row = next(m for m in machines.json() if m["hostname"] == "LAB-PC-077")
    assert row["current_ip"] == "192.168.1.77"
    machine_id = row["id"]

    second = await client.post(
        "/api/agents/heartbeat",
        headers=headers,
        json={"hostname": "LAB-PC-077", "ip_addresses": ["10.32.4.91"], "status": "healthy"},
    )
    assert second.status_code == 200
    after = await client.get(f"/api/machines/{machine_id}", headers=auth_headers)
    body = after.json()
    assert body["current_ip"] == "10.32.4.91"
    assert body["previous_ip"] == "192.168.1.77"
    assert "10.32.4.91" in body["current_ips"]
    events = await client.get(f"/api/machines/{machine_id}/events", headers=auth_headers)
    types = {e["event_type"] for e in events.json()}
    assert "IP_CHANGED" in types
    listed = await client.get("/api/machines", headers=auth_headers)
    ids = [m["id"] for m in listed.json() if m["hostname"] == "LAB-PC-077"]
    assert ids == [machine_id]


@pytest.mark.asyncio
async def test_invalid_agent_rejected(client: AsyncClient):
    r = await client.post("/api/agents/heartbeat", headers={"Authorization": "Bearer no:secret"}, json={"hostname": "x"})
    assert r.status_code == 401
