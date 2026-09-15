from sqlalchemy.dialects import postgresql

from app.db import BYTE_COLUMNS, VARCHAR_WIDEN, machine_address_column_sql
from app.models import MemorySlot, MetricSample, PcieSlot


def test_postgres_address_columns_use_pg_types():
    pg = machine_address_column_sql("postgresql")
    assert pg["current_ips"] == "JSONB"
    assert pg["ip_changed_at"] == "TIMESTAMPTZ"
    assert "DATETIME" not in pg.values()


def test_sqlite_address_columns_keep_generic_types():
    lite = machine_address_column_sql("sqlite")
    assert lite["current_ips"] == "JSON"
    assert lite["ip_changed_at"] == "DATETIME"


def test_byte_columns_compile_to_postgres_bigint():
    compiled = str(MetricSample.__table__.c.ram_total_bytes.type.compile(dialect=postgresql.dialect()))
    assert compiled.upper() == "BIGINT"
    names = {f"{table}.{column}" for table, column in BYTE_COLUMNS}
    assert "metric_samples.ram_total_bytes" in names
    assert "gpu_devices.vram_bytes" in names
    assert "gpu_metric_samples.vram_total_bytes" in names


def test_dmidecode_strings_are_wider_than_32():
    assert MemorySlot.__table__.c.ecc.type.length >= 120
    assert PcieSlot.__table__.c.generation.type.length >= 120
    widened = {(table, column): length for table, column, length in VARCHAR_WIDEN}
    assert widened[("memory_slots", "ecc")] >= 120
    assert widened[("pcie_slots", "generation")] >= 120
