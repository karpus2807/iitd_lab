import pytest
from httpx import AsyncClient

from app.schemas.inventory import GPUInfo, InventoryPayload, MemoryInfo, MemoryModule


@pytest.mark.asyncio
async def test_health(client: AsyncClient):
    r = await client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    assert r.json()["database"] == "ok"


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


@pytest.mark.asyncio
async def test_agent_logs_levels_and_inventory_notes(client: AsyncClient, auth_headers):
    tok = await client.post("/api/admin/tokens", headers=auth_headers, json={"label": "logs", "expires_hours": 24})
    reg = await client.post(
        "/api/agents/register",
        json={
            "registration_token": tok.json()["token"],
            "agent_uuid": "agent-logs-001",
            "agent_version": "1.1.18",
            "identity": {"hostname": "LOG-PC", "os_name": "Linux", "architecture": "x86_64", "system_uuid": "sys-logs-001"},
        },
    )
    assert reg.status_code == 200, reg.text
    headers = {"Authorization": f"Bearer {reg.json()['agent_id']}:{reg.json()['agent_secret']}"}
    machine_id = reg.json()["machine_id"]

    posted = await client.post(
        "/api/agents/logs",
        headers=headers,
        json=[
            {"level": "error", "message": "disk smart failed", "details": {"source": "agent"}},
            {"level": "WARN", "message": "dmidecode missing", "details": {"source": "agent"}},
            {"level": "info", "message": "agent started", "details": {"source": "agent"}},
            {"level": "debug", "message": "heartbeat ok", "details": {"source": "agent"}},
            {"level": "critical", "message": "agent crashed", "details": {"source": "agent"}},
        ],
    )
    assert posted.status_code == 200, posted.text

    inv = await client.post(
        "/api/agents/inventory",
        headers=headers,
        json={
            "identity": {"hostname": "LOG-PC", "os_name": "Linux", "architecture": "x86_64"},
            "collection_notes": ["dmidecode not installed; RAM slot topology not exposed."],
        },
    )
    assert inv.status_code == 200, inv.text

    listed = await client.get(f"/api/machines/{machine_id}/logs?limit=500", headers=auth_headers)
    assert listed.status_code == 200
    messages = [row["message"] for row in listed.json()]
    assert "disk smart failed" in messages
    assert "agent started" in messages
    assert any("dmidecode not installed" in m for m in messages)
    levels = {row["level"] for row in listed.json()}
    assert {"ERROR", "WARNING", "INFO", "DEBUG", "CRITICAL"} <= levels

    errors = await client.get(f"/api/machines/{machine_id}/logs?level=ERROR", headers=auth_headers)
    assert {row["level"] for row in errors.json()} == {"ERROR"}
    found = await client.get(f"/api/machines/{machine_id}/logs?q=started", headers=auth_headers)
    assert any("started" in row["message"] for row in found.json())

    machine = await client.get(f"/api/machines/{machine_id}", headers=auth_headers)
    assert machine.json()["last_seen_at"]


@pytest.mark.asyncio
async def test_inventory_metrics_accept_gpu_lab_sizes(client: AsyncClient, auth_headers):
    tok = await client.post("/api/admin/tokens", headers=auth_headers, json={"label": "gpu", "expires_hours": 24})
    reg = await client.post(
        "/api/agents/register",
        json={
            "registration_token": tok.json()["token"],
            "agent_uuid": "agent-gpu-lab-001",
            "agent_version": "1.1.18",
            "identity": {
                "hostname": "CLOUD-GPU-1",
                "os_name": "Linux",
                "architecture": "x86_64",
                "system_uuid": "sys-gpu-lab-001",
            },
        },
    )
    assert reg.status_code == 200, reg.text
    headers = {"Authorization": f"Bearer {reg.json()['agent_id']}:{reg.json()['agent_secret']}"}
    inv = await client.post(
        "/api/agents/inventory",
        headers=headers,
        json={
            "identity": {"hostname": "CLOUD-GPU-1", "os_name": "Linux", "architecture": "x86_64"},
            "memory": {
                "total_physical_bytes": 128 * 1024**3,
                "modules": [
                    {
                        "slot_locator": "DIMM_A1",
                        "occupied": True,
                        "capacity_bytes": 32 * 1024**3,
                        "ecc": "Synchronous Registered (Buffered)",
                        "rank": "2",
                    }
                ],
            },
            "gpus": [
                {
                    "index": 0,
                    "vendor": "NVIDIA",
                    "model": "NVIDIA A100-SXM4-80GB",
                    "vram_bytes": 80 * 1024**3,
                    "pci_bus": "00000000:01:00.0",
                    "driver_version": "550.127.05",
                }
            ],
            "pcie": {
                "slots": [
                    {
                        "slot_designation": "Slot 1",
                        "slot_type": "PCI Express 5 x16",
                        "generation": "PCI Express 5 x16",
                        "width": "16x or x16",
                    }
                ]
            },
            "storage": {"disks": [{"name": "nvme0n1", "capacity_bytes": 2 * 1024**4, "media_type": "NVMe"}]},
        },
    )
    assert inv.status_code == 200, inv.text
    metrics = await client.post(
        "/api/agents/metrics",
        headers=headers,
        json={
            "cpu_usage_pct": 11.0,
            "ram_used_bytes": 40 * 1024**3,
            "ram_total_bytes": 128 * 1024**3,
            "disk_used_bytes": 400 * 1024**3,
            "disk_total_bytes": 2 * 1024**4,
            "gpus": [
                {
                    "index": 0,
                    "utilization_pct": 80,
                    "vram_used_bytes": 60 * 1024**3,
                    "vram_total_bytes": 80 * 1024**3,
                }
            ],
        },
    )
    assert metrics.status_code == 200, metrics.text
    listed = await client.get(f"/api/machines/{reg.json()['machine_id']}/metrics?range=1h", headers=auth_headers)
    assert listed.status_code == 200, listed.text
    assert listed.json()["samples"], listed.text


@pytest.mark.asyncio
async def test_soc_inventory_and_clear_history_events_logs(client: AsyncClient, auth_headers):
    tok = await client.post("/api/admin/tokens", headers=auth_headers, json={"label": "soc", "expires_hours": 24})
    reg = await client.post(
        "/api/agents/register",
        json={
            "registration_token": tok.json()["token"],
            "agent_uuid": "agent-soc-orin-001",
            "agent_version": "1.1.20",
            "identity": {
                "hostname": "orin-agx",
                "os_name": "Linux",
                "architecture": "aarch64",
                "system_uuid": "sys-orin-001",
            },
        },
    )
    assert reg.status_code == 200, reg.text
    headers = {"Authorization": f"Bearer {reg.json()['agent_id']}:{reg.json()['agent_secret']}"}
    machine_id = reg.json()["machine_id"]
    inv = await client.post(
        "/api/agents/inventory",
        headers=headers,
        json={
            "identity": {"hostname": "orin-agx", "os_name": "Linux", "architecture": "aarch64"},
            "memory": {
                "total_physical_bytes": 61 * 1024**3,
                "used_bytes": 39 * 1024**3,
                "available_bytes": 22 * 1024**3,
                "usage_pct": 64.2,
                "topology_status": "SOC",
                "notes": ["Unified soldered memory (SoC); DIMM slot map does not apply."],
                "extra": {"memory_kind": "unified", "form_factor": "soldered", "memory_type": "LPDDR5", "speed_mts": 3200},
            },
            "gpus": [
                {
                    "index": 0,
                    "vendor": "NVIDIA",
                    "model": "NVIDIA Jetson AGX Orin",
                    "slot_designation": "SoC (nvgpu)",
                    "utilization_pct": 1.0,
                    "temperature_c": 38.375,
                    "power_w": 4.2,
                    "graphics_clock_mhz": 1300,
                    "memory_clock_mhz": 3200,
                    "driver_version": "540.5.0",
                    "vram_bytes": 61 * 1024**3,
                    "extra": {
                        "memory_kind": "unified",
                        "bus": "soc",
                        "platform": "jetson",
                        "unified_ram_bytes": 61 * 1024**3,
                        "board_power_w": 12.1,
                        "power_rails": {"VDD_GPU_SOC": 4.2, "VDD_IN": 12.1},
                    },
                }
            ],
            "pcie": {"topology_status": "SOC", "slots": [], "gpu_capable_total": 0},
        },
    )
    assert inv.status_code == 200, inv.text
    hw = await client.get(f"/api/machines/{machine_id}/hardware", headers=auth_headers)
    assert hw.status_code == 200, hw.text
    body = hw.json()
    assert body["memory"]["topology_status"] == "SOC"
    assert body["memory"]["extra"]["memory_kind"] == "unified"
    assert body["memory"]["extra"]["memory_type"] == "LPDDR5"
    assert body["gpus"][0]["pci_bus"] in (None, "")
    assert body["gpus"][0]["power_w"] == 4.2
    assert body["pcie"]["topology_status"] == "SOC"

    await client.post(
        "/api/agents/logs",
        headers=headers,
        json=[{"level": "info", "message": "agent started", "details": {"source": "agent"}}],
    )
    events = await client.get(f"/api/machines/{machine_id}/events", headers=auth_headers)
    assert events.json()
    logs = await client.get(f"/api/machines/{machine_id}/logs", headers=auth_headers)
    assert logs.json()

    cleared_events = await client.delete(f"/api/machines/{machine_id}/events", headers=auth_headers)
    assert cleared_events.status_code == 200, cleared_events.text
    assert (await client.get(f"/api/machines/{machine_id}/events", headers=auth_headers)).json() == []

    await client.post("/api/agents/inventory", headers=headers, json={"identity": {"hostname": "orin-agx"}})
    cleared_history = await client.delete(f"/api/machines/{machine_id}/history", headers=auth_headers)
    assert cleared_history.status_code == 200
    assert (await client.get(f"/api/machines/{machine_id}/events", headers=auth_headers)).json() == []

    cleared_logs = await client.delete(f"/api/machines/{machine_id}/logs", headers=auth_headers)
    assert cleared_logs.status_code == 200
    assert (await client.get(f"/api/machines/{machine_id}/logs", headers=auth_headers)).json() == []
