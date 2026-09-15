from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


Confidence = Literal["DETECTED", "REPORTED", "UNKNOWN"]
Topology = Literal["DETECTED", "PARTIAL", "UNKNOWN"]


class IdentityInfo(BaseModel):
    hostname: str = ""
    os_name: str = ""
    os_version: str = ""
    kernel_version: str | None = None
    architecture: str = ""
    machine_uuid: str | None = None
    system_uuid: str | None = None
    bios_uuid: str | None = None
    motherboard_serial: str | None = None
    system_serial: str | None = None
    mac_addresses: list[str] = Field(default_factory=list)
    agent_uuid: str | None = None
    is_virtual: bool = False
    virtualization: str | None = None
    notes: list[str] = Field(default_factory=list)


class OSInfo(BaseModel):
    name: str | None = None
    version: str | None = None
    kernel: str | None = None
    architecture: str | None = None
    hostname: str | None = None
    boot_time: datetime | None = None
    uptime_seconds: float | None = None


class CPUInfo(BaseModel):
    manufacturer: str | None = None
    model: str | None = None
    family: str | None = None
    architecture: str | None = None
    physical_sockets: int | None = None
    physical_cores: int | None = None
    logical_processors: int | None = None
    base_frequency_mhz: float | None = None
    current_frequency_mhz: float | None = None
    usage_pct: float | None = None
    temperature_c: float | None = None
    load_avg_1: float | None = None
    load_avg_5: float | None = None
    load_avg_15: float | None = None
    uptime_seconds: float | None = None
    topology_status: Topology = "PARTIAL"
    notes: list[str] = Field(default_factory=list)


class MemoryModule(BaseModel):
    slot_locator: str
    bank_locator: str | None = None
    occupied: bool = False
    capacity_bytes: int | None = None
    manufacturer: str | None = None
    part_number: str | None = None
    serial_number: str | None = None
    memory_type: str | None = None
    speed_mts: int | None = None
    configured_speed_mts: int | None = None
    ecc: str | None = None
    form_factor: str | None = None
    rank: str | None = None
    locator_known: bool = True


class MemoryInfo(BaseModel):
    total_physical_bytes: int | None = None
    max_supported_bytes: int | None = None
    slot_count: int | None = None
    occupied_slots: int | None = None
    free_slots: int | None = None
    used_bytes: int | None = None
    available_bytes: int | None = None
    usage_pct: float | None = None
    topology_status: Topology = "UNKNOWN"
    unlocated_empty_slots: int | None = None
    modules: list[MemoryModule] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class GPUInfo(BaseModel):
    index: int = 0
    vendor: str | None = None
    model: str | None = None
    vram_bytes: int | None = None
    pci_bus: str | None = None
    pci_device_id: str | None = None
    serial_number: str | None = None
    uuid: str | None = None
    driver_version: str | None = None
    utilization_pct: float | None = None
    temperature_c: float | None = None
    power_w: float | None = None
    graphics_clock_mhz: float | None = None
    memory_clock_mhz: float | None = None
    slot_designation: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class PCIeSlotInfo(BaseModel):
    slot_designation: str
    slot_type: str | None = None
    generation: str | None = None
    width: str | None = None
    current_usage: str | None = None
    occupied: bool | None = None
    is_gpu_capable: bool | None = None
    attached_device: str | None = None
    bus_address: str | None = None


class PCIeInfo(BaseModel):
    topology_status: Topology = "UNKNOWN"
    topology_note: str | None = None
    slots: list[PCIeSlotInfo] = Field(default_factory=list)
    gpu_capable_total: int | None = None
    gpu_capable_occupied: int | None = None
    gpu_capable_free: int | None = None
    pci_devices: list[dict[str, Any]] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class DiskInfo(BaseModel):
    name: str = ""
    model: str | None = None
    serial_number: str | None = None
    capacity_bytes: int | None = None
    interface: str | None = None
    media_type: str | None = None
    smart_status: str | None = None
    temperature_c: float | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class FilesystemInfo(BaseModel):
    mountpoint: str
    fstype: str | None = None
    device: str | None = None
    total_bytes: int | None = None
    used_bytes: int | None = None


class StorageInfo(BaseModel):
    disks: list[DiskInfo] = Field(default_factory=list)
    filesystems: list[FilesystemInfo] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class NicInfo(BaseModel):
    name: str
    mac: str | None = None
    ipv4: list[str] = Field(default_factory=list)
    ipv6: list[str] = Field(default_factory=list)
    is_up: bool = False
    speed_mbps: int | None = None
    rx_bytes: int | None = None
    tx_bytes: int | None = None


class NetworkInfo(BaseModel):
    hostname: str | None = None
    interfaces: list[NicInfo] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class MotherboardInfo(BaseModel):
    manufacturer: str | None = None
    model: str | None = None
    serial_number: str | None = None
    version: str | None = None
    notes: list[str] = Field(default_factory=list)


class BIOSInfo(BaseModel):
    vendor: str | None = None
    version: str | None = None
    release_date: str | None = None
    system_manufacturer: str | None = None
    system_model: str | None = None
    system_serial: str | None = None
    system_uuid: str | None = None
    notes: list[str] = Field(default_factory=list)


class InventoryPayload(BaseModel):
    collected_at: datetime | None = None
    identity: IdentityInfo = Field(default_factory=IdentityInfo)
    os: OSInfo = Field(default_factory=OSInfo)
    cpu: CPUInfo = Field(default_factory=CPUInfo)
    memory: MemoryInfo = Field(default_factory=MemoryInfo)
    gpus: list[GPUInfo] = Field(default_factory=list)
    pcie: PCIeInfo = Field(default_factory=PCIeInfo)
    storage: StorageInfo = Field(default_factory=StorageInfo)
    network: NetworkInfo = Field(default_factory=NetworkInfo)
    motherboard: MotherboardInfo = Field(default_factory=MotherboardInfo)
    bios: BIOSInfo = Field(default_factory=BIOSInfo)
    collection_notes: list[str] = Field(default_factory=list)


class GpuMetric(BaseModel):
    index: int = 0
    gpu_key: str = ""
    utilization_pct: float | None = None
    temperature_c: float | None = None
    vram_used_bytes: int | None = None
    vram_total_bytes: int | None = None
    power_w: float | None = None
    graphics_clock_mhz: float | None = None
    memory_clock_mhz: float | None = None


class MetricsPayload(BaseModel):
    collected_at: datetime | None = None
    cpu_usage_pct: float | None = None
    cpu_temp_c: float | None = None
    cpu_freq_mhz: float | None = None
    ram_used_bytes: int | None = None
    ram_total_bytes: int | None = None
    ram_available_bytes: int | None = None
    ram_usage_pct: float | None = None
    disk_read_bps: float | None = None
    disk_write_bps: float | None = None
    disk_used_bytes: int | None = None
    disk_total_bytes: int | None = None
    net_tx_bps: float | None = None
    net_rx_bps: float | None = None
    gpus: list[GpuMetric] = Field(default_factory=list)


class HeartbeatPayload(BaseModel):
    agent_version: str = ""
    hostname: str = ""
    ip_addresses: list[str] = Field(default_factory=list)
    mac_addresses: list[str] = Field(default_factory=list)
    status: Literal["healthy", "degraded"] = "healthy"
    uptime_seconds: float | None = None
    collector_errors: list[str] = Field(default_factory=list)


class AgentEventPayload(BaseModel):
    event_type: str
    severity: str = "INFO"
    summary: str = ""
    component_path: str = ""
    previous_value: dict[str, Any] | None = None
    new_value: dict[str, Any] | None = None
    created_at: datetime | None = None


class AgentLogPayload(BaseModel):
    level: str = "INFO"
    message: str
    details: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None


class DiffEvent(BaseModel):
    event_type: str
    severity: str
    component_path: str
    previous_value: dict[str, Any] | None = None
    new_value: dict[str, Any] | None = None
    summary: str
