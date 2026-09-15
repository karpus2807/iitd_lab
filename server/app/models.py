from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import Boolean, ForeignKey, Index, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, json_column, TZDateTime


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        TZDateTime(), default=utcnow, onupdate=utcnow
    )


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    username: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[str] = mapped_column(String(255), default="")
    role: Mapped[str] = mapped_column(String(32), default="VIEWER", index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_login_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)

    refresh_tokens: Mapped[list["RefreshToken"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(TZDateTime())
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow)

    user: Mapped[User] = relationship(back_populates="refresh_tokens")


class Lab(Base, TimestampMixin):
    __tablename__ = "labs"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    code: Mapped[str] = mapped_column(String(32), default="")
    department: Mapped[str] = mapped_column(String(120), default="")
    building: Mapped[str] = mapped_column(String(120), default="")
    floor: Mapped[str] = mapped_column(String(32), default="")
    room: Mapped[str] = mapped_column(String(64), default="")
    capacity: Mapped[int] = mapped_column(Integer, default=0)
    incharge: Mapped[str] = mapped_column(String(120), default="")
    phone: Mapped[str] = mapped_column(String(64), default="")
    email: Mapped[str] = mapped_column(String(255), default="")
    description: Mapped[str] = mapped_column(Text, default="")

    machines: Mapped[list["Machine"]] = relationship(back_populates="lab")


class Machine(Base, TimestampMixin):
    __tablename__ = "machines"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    lab_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("labs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    hostname: Mapped[str] = mapped_column(String(255), default="", index=True)
    display_name: Mapped[str] = mapped_column(String(255), default="")
    os_name: Mapped[str] = mapped_column(String(120), default="")
    os_version: Mapped[str] = mapped_column(String(120), default="")
    kernel_version: Mapped[str] = mapped_column(String(120), default="")
    architecture: Mapped[str] = mapped_column(String(64), default="")
    machine_uuid: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    system_uuid: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    motherboard_serial: Mapped[str | None] = mapped_column(String(128), nullable=True)
    system_serial: Mapped[str | None] = mapped_column(String(128), nullable=True)
    is_virtual: Mapped[bool] = mapped_column(Boolean, default=False)
    virtualization: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="NEVER_CONNECTED", index=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True, index=True)
    first_seen_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    current_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    current_ips: Mapped[list] = mapped_column(json_column(), default=list)
    previous_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ip_changed_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    approved: Mapped[bool] = mapped_column(Boolean, default=True)
    has_open_alerts: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    last_hardware_change_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    gpu_count: Mapped[int] = mapped_column(Integer, default=0)
    identity_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)

    lab: Mapped[Lab | None] = relationship(back_populates="machines")
    agent: Mapped["Agent | None"] = relationship(back_populates="machine", uselist=False)


class Agent(Base, TimestampMixin):
    __tablename__ = "agents"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    machine_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("machines.id", ondelete="CASCADE"), unique=True
    )
    agent_public_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    secret_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), default="ACTIVE", index=True)
    agent_version: Mapped[str] = mapped_column(String(32), default="")
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    last_inventory_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    last_metrics_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    health: Mapped[str] = mapped_column(String(32), default="unknown")
    revoked_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    registration_token_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("registration_tokens.id", ondelete="SET NULL"), nullable=True
    )

    machine: Mapped[Machine] = relationship(back_populates="agent")


class RegistrationToken(Base, TimestampMixin):
    __tablename__ = "registration_tokens"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    token_prefix: Mapped[str] = mapped_column(String(12), default="")
    label: Mapped[str] = mapped_column(String(120), default="")
    lab_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("labs.id", ondelete="SET NULL"), nullable=True
    )
    created_by_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    expires_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    max_uses: Mapped[int | None] = mapped_column(Integer, nullable=True)
    use_count: Mapped[int] = mapped_column(Integer, default=0)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    token_plaintext_once: Mapped[str | None] = mapped_column(String(128), nullable=True)


class CpuInventory(Base, TimestampMixin):
    __tablename__ = "cpu_inventory"

    machine_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("machines.id", ondelete="CASCADE"), primary_key=True
    )
    manufacturer: Mapped[str | None] = mapped_column(String(120), nullable=True)
    model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    family: Mapped[str | None] = mapped_column(String(120), nullable=True)
    architecture: Mapped[str | None] = mapped_column(String(64), nullable=True)
    physical_sockets: Mapped[int | None] = mapped_column(Integer, nullable=True)
    physical_cores: Mapped[int | None] = mapped_column(Integer, nullable=True)
    logical_processors: Mapped[int | None] = mapped_column(Integer, nullable=True)
    base_frequency_mhz: Mapped[float | None] = mapped_column(nullable=True)
    current_frequency_mhz: Mapped[float | None] = mapped_column(nullable=True)
    usage_pct: Mapped[float | None] = mapped_column(nullable=True)
    temperature_c: Mapped[float | None] = mapped_column(nullable=True)
    load_avg_1: Mapped[float | None] = mapped_column(nullable=True)
    load_avg_5: Mapped[float | None] = mapped_column(nullable=True)
    load_avg_15: Mapped[float | None] = mapped_column(nullable=True)
    uptime_seconds: Mapped[float | None] = mapped_column(nullable=True)
    topology_status: Mapped[str] = mapped_column(String(32), default="PARTIAL")
    notes: Mapped[list] = mapped_column(json_column(), default=list)
    raw: Mapped[dict] = mapped_column(json_column(), default=dict)


class MemorySummary(Base, TimestampMixin):
    __tablename__ = "memory_summaries"

    machine_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("machines.id", ondelete="CASCADE"), primary_key=True
    )
    total_physical_bytes: Mapped[int | None] = mapped_column(nullable=True)
    max_supported_bytes: Mapped[int | None] = mapped_column(nullable=True)
    slot_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    occupied_slots: Mapped[int | None] = mapped_column(Integer, nullable=True)
    free_slots: Mapped[int | None] = mapped_column(Integer, nullable=True)
    used_bytes: Mapped[int | None] = mapped_column(nullable=True)
    available_bytes: Mapped[int | None] = mapped_column(nullable=True)
    usage_pct: Mapped[float | None] = mapped_column(nullable=True)
    topology_status: Mapped[str] = mapped_column(String(32), default="UNKNOWN")
    unlocated_empty_slots: Mapped[int | None] = mapped_column(Integer, nullable=True)
    notes: Mapped[list] = mapped_column(json_column(), default=list)


class MemorySlot(Base):
    __tablename__ = "memory_slots"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    machine_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("machines.id", ondelete="CASCADE"), index=True
    )
    slot_locator: Mapped[str] = mapped_column(String(120))
    bank_locator: Mapped[str | None] = mapped_column(String(120), nullable=True)
    occupied: Mapped[bool] = mapped_column(Boolean, default=False)
    capacity_bytes: Mapped[int | None] = mapped_column(nullable=True)
    manufacturer: Mapped[str | None] = mapped_column(String(120), nullable=True)
    part_number: Mapped[str | None] = mapped_column(String(120), nullable=True)
    serial_number: Mapped[str | None] = mapped_column(String(120), nullable=True)
    memory_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    speed_mts: Mapped[int | None] = mapped_column(Integer, nullable=True)
    configured_speed_mts: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ecc: Mapped[str | None] = mapped_column(String(32), nullable=True)
    form_factor: Mapped[str | None] = mapped_column(String(64), nullable=True)
    rank: Mapped[str | None] = mapped_column(String(32), nullable=True)
    locator_known: Mapped[bool] = mapped_column(Boolean, default=True)
    extra: Mapped[dict] = mapped_column(json_column(), default=dict)


class GpuDevice(Base, TimestampMixin):
    __tablename__ = "gpu_devices"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    machine_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("machines.id", ondelete="CASCADE"), index=True
    )
    gpu_index: Mapped[int] = mapped_column(Integer, default=0)
    vendor: Mapped[str | None] = mapped_column(String(120), nullable=True)
    model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    vram_bytes: Mapped[int | None] = mapped_column(nullable=True)
    pci_bus: Mapped[str | None] = mapped_column(String(64), nullable=True)
    pci_device_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    serial_number: Mapped[str | None] = mapped_column(String(120), nullable=True)
    uuid: Mapped[str | None] = mapped_column(String(128), nullable=True)
    driver_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    utilization_pct: Mapped[float | None] = mapped_column(nullable=True)
    temperature_c: Mapped[float | None] = mapped_column(nullable=True)
    power_w: Mapped[float | None] = mapped_column(nullable=True)
    graphics_clock_mhz: Mapped[float | None] = mapped_column(nullable=True)
    memory_clock_mhz: Mapped[float | None] = mapped_column(nullable=True)
    slot_designation: Mapped[str | None] = mapped_column(String(120), nullable=True)
    extra: Mapped[dict] = mapped_column(json_column(), default=dict)


class PcieSlot(Base):
    __tablename__ = "pcie_slots"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    machine_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("machines.id", ondelete="CASCADE"), index=True
    )
    slot_designation: Mapped[str] = mapped_column(String(120))
    slot_type: Mapped[str | None] = mapped_column(String(120), nullable=True)
    generation: Mapped[str | None] = mapped_column(String(32), nullable=True)
    width: Mapped[str | None] = mapped_column(String(32), nullable=True)
    current_usage: Mapped[str | None] = mapped_column(String(120), nullable=True)
    occupied: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    is_gpu_capable: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    attached_device: Mapped[str | None] = mapped_column(String(255), nullable=True)
    bus_address: Mapped[str | None] = mapped_column(String(64), nullable=True)


class PcieTopology(Base, TimestampMixin):
    __tablename__ = "pcie_topologies"

    machine_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("machines.id", ondelete="CASCADE"), primary_key=True
    )
    topology_status: Mapped[str] = mapped_column(String(32), default="UNKNOWN")
    topology_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    gpu_capable_total: Mapped[int | None] = mapped_column(Integer, nullable=True)
    gpu_capable_occupied: Mapped[int | None] = mapped_column(Integer, nullable=True)
    gpu_capable_free: Mapped[int | None] = mapped_column(Integer, nullable=True)
    notes: Mapped[list] = mapped_column(json_column(), default=list)


class StorageDevice(Base, TimestampMixin):
    __tablename__ = "storage_devices"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    machine_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("machines.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(120), default="")
    model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    serial_number: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    capacity_bytes: Mapped[int | None] = mapped_column(nullable=True)
    interface: Mapped[str | None] = mapped_column(String(64), nullable=True)
    media_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    smart_status: Mapped[str | None] = mapped_column(String(64), nullable=True)
    temperature_c: Mapped[float | None] = mapped_column(nullable=True)
    extra: Mapped[dict] = mapped_column(json_column(), default=dict)


class Filesystem(Base):
    __tablename__ = "filesystems"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    machine_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("machines.id", ondelete="CASCADE"), index=True
    )
    mountpoint: Mapped[str] = mapped_column(String(255))
    fstype: Mapped[str | None] = mapped_column(String(64), nullable=True)
    device: Mapped[str | None] = mapped_column(String(120), nullable=True)
    total_bytes: Mapped[int | None] = mapped_column(nullable=True)
    used_bytes: Mapped[int | None] = mapped_column(nullable=True)


class NetworkInterface(Base):
    __tablename__ = "network_interfaces"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    machine_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("machines.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(120))
    mac: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    ipv4: Mapped[list] = mapped_column(json_column(), default=list)
    ipv6: Mapped[list] = mapped_column(json_column(), default=list)
    is_up: Mapped[bool] = mapped_column(Boolean, default=False)
    speed_mbps: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rx_bytes: Mapped[int | None] = mapped_column(nullable=True)
    tx_bytes: Mapped[int | None] = mapped_column(nullable=True)


class Motherboard(Base, TimestampMixin):
    __tablename__ = "motherboards"

    machine_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("machines.id", ondelete="CASCADE"), primary_key=True
    )
    manufacturer: Mapped[str | None] = mapped_column(String(120), nullable=True)
    model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    serial_number: Mapped[str | None] = mapped_column(String(120), nullable=True)
    version: Mapped[str | None] = mapped_column(String(64), nullable=True)


class Bios(Base, TimestampMixin):
    __tablename__ = "bios"

    machine_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("machines.id", ondelete="CASCADE"), primary_key=True
    )
    vendor: Mapped[str | None] = mapped_column(String(120), nullable=True)
    version: Mapped[str | None] = mapped_column(String(120), nullable=True)
    release_date: Mapped[str | None] = mapped_column(String(64), nullable=True)
    system_manufacturer: Mapped[str | None] = mapped_column(String(120), nullable=True)
    system_model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    system_serial: Mapped[str | None] = mapped_column(String(120), nullable=True)
    system_uuid: Mapped[str | None] = mapped_column(String(128), nullable=True)


class HardwareSnapshot(Base):
    __tablename__ = "hardware_snapshots"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    machine_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("machines.id", ondelete="CASCADE"), index=True
    )
    collected_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow, index=True)
    payload: Mapped[dict] = mapped_column(json_column())
    fingerprint: Mapped[str] = mapped_column(String(64), default="", index=True)


class HardwareEvent(Base):
    __tablename__ = "hardware_events"
    __table_args__ = (Index("ix_hw_events_machine_time", "machine_id", "created_at"),)

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    machine_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("machines.id", ondelete="CASCADE"), index=True
    )
    event_type: Mapped[str] = mapped_column(String(64), index=True)
    severity: Mapped[str] = mapped_column(String(32), default="INFO", index=True)
    component_path: Mapped[str] = mapped_column(String(255), default="")
    previous_value: Mapped[dict | None] = mapped_column(json_column(), nullable=True)
    new_value: Mapped[dict | None] = mapped_column(json_column(), nullable=True)
    summary: Mapped[str] = mapped_column(Text, default="")
    detected_by: Mapped[str] = mapped_column(String(32), default="SERVER")
    acknowledged: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    acknowledged_by_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    acknowledged_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow, index=True)


class MetricSample(Base):
    __tablename__ = "metric_samples"
    __table_args__ = (Index("ix_metric_samples_machine_time", "machine_id", "collected_at"),)

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    machine_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("machines.id", ondelete="CASCADE"), index=True
    )
    collected_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow, index=True)
    cpu_usage_pct: Mapped[float | None] = mapped_column(nullable=True)
    cpu_temp_c: Mapped[float | None] = mapped_column(nullable=True)
    cpu_freq_mhz: Mapped[float | None] = mapped_column(nullable=True)
    ram_used_bytes: Mapped[int | None] = mapped_column(nullable=True)
    ram_total_bytes: Mapped[int | None] = mapped_column(nullable=True)
    ram_available_bytes: Mapped[int | None] = mapped_column(nullable=True)
    ram_usage_pct: Mapped[float | None] = mapped_column(nullable=True)
    disk_read_bps: Mapped[float | None] = mapped_column(nullable=True)
    disk_write_bps: Mapped[float | None] = mapped_column(nullable=True)
    disk_used_bytes: Mapped[int | None] = mapped_column(nullable=True)
    disk_total_bytes: Mapped[int | None] = mapped_column(nullable=True)
    net_tx_bps: Mapped[float | None] = mapped_column(nullable=True)
    net_rx_bps: Mapped[float | None] = mapped_column(nullable=True)


class GpuMetricSample(Base):
    __tablename__ = "gpu_metric_samples"
    __table_args__ = (Index("ix_gpu_metrics_machine_time", "machine_id", "collected_at"),)

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    machine_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("machines.id", ondelete="CASCADE"), index=True
    )
    gpu_index: Mapped[int] = mapped_column(Integer, default=0)
    gpu_key: Mapped[str] = mapped_column(String(128), default="")
    collected_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow, index=True)
    utilization_pct: Mapped[float | None] = mapped_column(nullable=True)
    temperature_c: Mapped[float | None] = mapped_column(nullable=True)
    vram_used_bytes: Mapped[int | None] = mapped_column(nullable=True)
    vram_total_bytes: Mapped[int | None] = mapped_column(nullable=True)
    power_w: Mapped[float | None] = mapped_column(nullable=True)
    graphics_clock_mhz: Mapped[float | None] = mapped_column(nullable=True)
    memory_clock_mhz: Mapped[float | None] = mapped_column(nullable=True)


class MetricHourly(Base):
    __tablename__ = "metric_hourly"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    machine_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("machines.id", ondelete="CASCADE"), index=True
    )
    hour_start: Mapped[datetime] = mapped_column(TZDateTime(), index=True)
    sample_count: Mapped[int] = mapped_column(Integer, default=0)
    values: Mapped[dict] = mapped_column(json_column(), default=dict)


class AlertRule(Base, TimestampMixin):
    __tablename__ = "alert_rules"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    description: Mapped[str] = mapped_column(Text, default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    severity: Mapped[str] = mapped_column(String(32), default="WARNING")
    rule_type: Mapped[str] = mapped_column(String(32))  # EVENT or METRIC
    event_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    metric_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    operator: Mapped[str] = mapped_column(String(8), default=">")
    threshold: Mapped[float | None] = mapped_column(nullable=True)
    cooldown_seconds: Mapped[int] = mapped_column(Integer, default=900)


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    machine_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("machines.id", ondelete="CASCADE"), nullable=True, index=True
    )
    rule_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("alert_rules.id", ondelete="SET NULL"), nullable=True
    )
    severity: Mapped[str] = mapped_column(String(32), default="WARNING", index=True)
    status: Mapped[str] = mapped_column(String(32), default="OPEN", index=True)
    title: Mapped[str] = mapped_column(String(255))
    message: Mapped[str] = mapped_column(Text, default="")
    event_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow, onupdate=utcnow)
    acknowledged_by_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    acknowledged_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    channel: Mapped[str] = mapped_column(String(32), default="DASHBOARD")
    title: Mapped[str] = mapped_column(String(255))
    body: Mapped[str] = mapped_column(Text, default="")
    payload: Mapped[dict] = mapped_column(json_column(), default=dict)
    read: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow, index=True)


class NotificationChannelConfig(Base, TimestampMixin):
    __tablename__ = "notification_channel_configs"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    channel: Mapped[str] = mapped_column(String(32), unique=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    config: Mapped[dict] = mapped_column(json_column(), default=dict)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow, index=True)
    user_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    username: Mapped[str | None] = mapped_column(String(80), nullable=True)
    machine_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(120), index=True)
    details: Mapped[dict] = mapped_column(json_column(), default=dict)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)


class AgentLog(Base):
    __tablename__ = "agent_logs"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    machine_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("machines.id", ondelete="CASCADE"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow, index=True)
    level: Mapped[str] = mapped_column(String(16), default="INFO")
    message: Mapped[str] = mapped_column(Text)
    details: Mapped[dict] = mapped_column(json_column(), default=dict)


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(120), primary_key=True)
    value: Mapped[dict] = mapped_column(json_column(), default=dict)
    updated_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow, onupdate=utcnow)
