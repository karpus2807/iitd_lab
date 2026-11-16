from collections.abc import AsyncGenerator
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, TypeDecorator
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings


def json_column():
    return JSON().with_variant(JSONB(), "postgresql")


class TZDateTime(TypeDecorator):
    """Store UTC naive timestamps; return timezone-aware UTC datetimes.

    PostgreSQL TIMESTAMP WITHOUT TIME ZONE (asyncpg) rejects aware datetimes.
    """

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is not None:
            value = value.astimezone(timezone.utc).replace(tzinfo=None)
        return value

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


class Base(DeclarativeBase):
    pass


_engine: AsyncEngine | None = None
SessionLocal: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    global _engine, SessionLocal
    if _engine is None:
        settings = get_settings()
        _engine = create_async_engine(
            settings.database_url,
            echo=False,
            pool_pre_ping=not settings.is_sqlite,
            connect_args={"check_same_thread": False} if settings.is_sqlite else {},
        )
        if settings.is_sqlite:
            from sqlalchemy import event

            @event.listens_for(_engine.sync_engine, "connect")
            def _sqlite_fk(dbapi_connection, _connection_record):
                cursor = dbapi_connection.cursor()
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.close()

        SessionLocal = async_sessionmaker(_engine, class_=AsyncSession, expire_on_commit=False)
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    get_engine()
    assert SessionLocal is not None
    return SessionLocal


def reset_engine() -> None:
    global _engine, SessionLocal
    _engine = None
    SessionLocal = None
    get_settings.cache_clear()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    factory = get_session_factory()
    async with factory() as session:
        yield session


async def init_models() -> None:
    from app import models  # noqa: F401

    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_ensure_machine_address_columns)
        await conn.run_sync(ensure_machine_inventory_column)
        await conn.run_sync(ensure_machine_pet_name_column)
        await conn.run_sync(ensure_lab_columns)
        await conn.run_sync(ensure_hardware_column_types)
        await conn.run_sync(ensure_memory_extra_column)
        await conn.run_sync(ensure_agent_update_columns)
        await conn.run_sync(ensure_inventory_assigned_column)
        await conn.run_sync(ensure_inventory_assign_meta_columns)
        await conn.run_sync(ensure_inventory_assignments_table)
        await conn.run_sync(ensure_scholar_removal_columns)
        await conn.run_sync(ensure_scholar_inv_verify_doc_column)
        await conn.run_sync(ensure_scholar_bio_approve_columns)
        await conn.run_sync(ensure_registration_token_last_used)


def machine_address_column_sql(dialect_name: str) -> dict[str, str]:
    if dialect_name == "postgresql":
        return {
            "current_ips": "JSONB",
            "previous_ip": "VARCHAR(64)",
            "ip_changed_at": "TIMESTAMPTZ",
        }
    return {
        "current_ips": "JSON",
        "previous_ip": "VARCHAR(64)",
        "ip_changed_at": "DATETIME",
    }


def _ensure_machine_address_columns(sync_conn) -> None:
    from sqlalchemy import inspect, text

    insp = inspect(sync_conn)
    if "machines" not in insp.get_table_names():
        return
    existing = {c["name"] for c in insp.get_columns("machines")}
    for name, sql_type in machine_address_column_sql(sync_conn.dialect.name).items():
        if name not in existing:
            sync_conn.execute(text(f"ALTER TABLE machines ADD COLUMN {name} {sql_type}"))


def ensure_machine_inventory_column(sync_conn) -> None:
    from sqlalchemy import inspect, text

    insp = inspect(sync_conn)
    if "machines" not in insp.get_table_names():
        return
    existing = {c["name"] for c in insp.get_columns("machines")}
    if "inventory_id" not in existing:
        sync_conn.execute(text("ALTER TABLE machines ADD COLUMN inventory_id VARCHAR(64)"))
    try:
        sync_conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_machines_inventory_id ON machines (inventory_id)"))
    except Exception:
        pass


def ensure_machine_pet_name_column(sync_conn) -> None:
    from sqlalchemy import inspect, text

    insp = inspect(sync_conn)
    if "machines" not in insp.get_table_names():
        return
    existing = {c["name"] for c in insp.get_columns("machines")}
    if "pet_name" not in existing:
        sync_conn.execute(text("ALTER TABLE machines ADD COLUMN pet_name VARCHAR(255) DEFAULT ''"))


def ensure_lab_columns(sync_conn) -> None:
    from sqlalchemy import inspect, text

    insp = inspect(sync_conn)
    if "labs" not in insp.get_table_names():
        return
    existing = {c["name"] for c in insp.get_columns("labs")}
    columns = (
        ("building", "VARCHAR(120) DEFAULT ''"),
        ("room", "VARCHAR(64) DEFAULT ''"),
        ("code", "VARCHAR(32) DEFAULT ''"),
        ("department", "VARCHAR(120) DEFAULT ''"),
        ("floor", "VARCHAR(32) DEFAULT ''"),
        ("capacity", "INTEGER DEFAULT 0"),
        ("incharge", "VARCHAR(120) DEFAULT ''"),
        ("phone", "VARCHAR(64) DEFAULT ''"),
        ("email", "VARCHAR(255) DEFAULT ''"),
    )
    for name, sql_type in columns:
        if name not in existing:
            sync_conn.execute(text(f"ALTER TABLE labs ADD COLUMN {name} {sql_type}"))


def lab_column_names(sync_conn) -> list[str]:
    from sqlalchemy import inspect

    insp = inspect(sync_conn)
    if "labs" not in insp.get_table_names():
        return []
    return [c["name"] for c in insp.get_columns("labs")]


# Postgres INTEGER is 32-bit; lab RAM/VRAM/disks overflow it. SQLite already stores 64-bit.
BYTE_COLUMNS = (
    ("memory_summaries", "total_physical_bytes"),
    ("memory_summaries", "max_supported_bytes"),
    ("memory_summaries", "used_bytes"),
    ("memory_summaries", "available_bytes"),
    ("memory_slots", "capacity_bytes"),
    ("gpu_devices", "vram_bytes"),
    ("storage_devices", "capacity_bytes"),
    ("filesystems", "total_bytes"),
    ("filesystems", "used_bytes"),
    ("network_interfaces", "rx_bytes"),
    ("network_interfaces", "tx_bytes"),
    ("metric_samples", "ram_used_bytes"),
    ("metric_samples", "ram_total_bytes"),
    ("metric_samples", "ram_available_bytes"),
    ("metric_samples", "disk_used_bytes"),
    ("metric_samples", "disk_total_bytes"),
    ("gpu_metric_samples", "vram_used_bytes"),
    ("gpu_metric_samples", "vram_total_bytes"),
)

# dmidecode Type Detail / PCIe type strings exceed the original VARCHAR(32).
VARCHAR_WIDEN = (
    ("memory_slots", "ecc", 120),
    ("memory_slots", "rank", 64),
    ("memory_slots", "memory_type", 120),
    ("pcie_slots", "generation", 120),
    ("pcie_slots", "width", 64),
    ("gpu_devices", "pci_bus", 128),
    ("gpu_devices", "driver_version", 128),
    ("storage_devices", "media_type", 64),
    ("machines", "os_version", 255),
    ("machines", "kernel_version", 255),
    ("machines", "virtualization", 120),
    ("motherboards", "version", 120),
)


def _column_type_name(col) -> str:
    return str(col.get("type") or "").upper()


def _is_bigint_type(col) -> bool:
    name = _column_type_name(col)
    return "BIGINT" in name or "BIGINTEGER" in name


def ensure_hardware_column_types(sync_conn) -> None:
    """Widen existing Postgres columns created before byte/string size fixes."""
    if sync_conn.dialect.name != "postgresql":
        return
    from sqlalchemy import inspect, text

    insp = inspect(sync_conn)
    tables = set(insp.get_table_names())
    for table, column in BYTE_COLUMNS:
        if table not in tables:
            continue
        cols = {c["name"]: c for c in insp.get_columns(table)}
        col = cols.get(column)
        if col is None or _is_bigint_type(col):
            continue
        sync_conn.execute(text(f"ALTER TABLE {table} ALTER COLUMN {column} TYPE BIGINT"))
    for table, column, length in VARCHAR_WIDEN:
        if table not in tables:
            continue
        cols = {c["name"]: c for c in insp.get_columns(table)}
        col = cols.get(column)
        if col is None:
            continue
        current = getattr(col.get("type"), "length", None)
        if current is not None and current >= length:
            continue
        sync_conn.execute(text(f"ALTER TABLE {table} ALTER COLUMN {column} TYPE VARCHAR({length})"))


def ensure_memory_extra_column(sync_conn) -> None:
    from sqlalchemy import inspect, text

    insp = inspect(sync_conn)
    if "memory_summaries" not in insp.get_table_names():
        return
    existing = {c["name"] for c in insp.get_columns("memory_summaries")}
    if "extra" in existing:
        return
    sql_type = "JSONB" if sync_conn.dialect.name == "postgresql" else "JSON"
    sync_conn.execute(text(f"ALTER TABLE memory_summaries ADD COLUMN extra {sql_type}"))


def ensure_agent_update_columns(sync_conn) -> None:
    from sqlalchemy import inspect, text

    insp = inspect(sync_conn)
    if "agents" not in insp.get_table_names():
        return
    existing = {c["name"] for c in insp.get_columns("agents")}
    if sync_conn.dialect.name == "postgresql":
        types = {
            "update_requested_at": "TIMESTAMPTZ",
            "update_status": "VARCHAR(32) DEFAULT ''",
            "update_command_id": "VARCHAR(64) DEFAULT ''",
            "update_message": "VARCHAR(512) DEFAULT ''",
            "update_target_version": "VARCHAR(32) DEFAULT ''",
        }
    else:
        types = {
            "update_requested_at": "DATETIME",
            "update_status": "VARCHAR(32) DEFAULT ''",
            "update_command_id": "VARCHAR(64) DEFAULT ''",
            "update_message": "VARCHAR(512) DEFAULT ''",
            "update_target_version": "VARCHAR(32) DEFAULT ''",
        }
    for name, sql_type in types.items():
        if name not in existing:
            sync_conn.execute(text(f"ALTER TABLE agents ADD COLUMN {name} {sql_type}"))


def ensure_inventory_assigned_column(sync_conn) -> None:
    from sqlalchemy import inspect, text

    insp = inspect(sync_conn)
    if "inventory_items" not in insp.get_table_names():
        return
    existing = {c["name"] for c in insp.get_columns("inventory_items")}
    if "assigned_to" not in existing:
        sync_conn.execute(text("ALTER TABLE inventory_items ADD COLUMN assigned_to VARCHAR(255) DEFAULT ''"))


def ensure_inventory_assign_meta_columns(sync_conn) -> None:
    from sqlalchemy import inspect, text

    insp = inspect(sync_conn)
    if "inventory_items" not in insp.get_table_names():
        return
    existing = {c["name"] for c in insp.get_columns("inventory_items")}
    if sync_conn.dialect.name == "postgresql":
        types = {
            "assigned_scholar_id": "UUID",
            "assigned_at": "TIMESTAMPTZ",
            "assigned_by": "VARCHAR(80) DEFAULT ''",
            "assign_verify_method": "VARCHAR(16) DEFAULT ''",
            "assign_verify_doc_path": "VARCHAR(512) DEFAULT ''",
            "revoked_from": "VARCHAR(255) DEFAULT ''",
            "revoked_from_scholar_id": "VARCHAR(120) DEFAULT ''",
            "revoked_from_bio_id": "VARCHAR(64) DEFAULT ''",
            "revoked_from_email": "VARCHAR(255) DEFAULT ''",
            "revoked_lab_name": "VARCHAR(255) DEFAULT ''",
        }
    else:
        types = {
            "assigned_scholar_id": "CHAR(32)",
            "assigned_at": "DATETIME",
            "assigned_by": "VARCHAR(80) DEFAULT ''",
            "assign_verify_method": "VARCHAR(16) DEFAULT ''",
            "assign_verify_doc_path": "VARCHAR(512) DEFAULT ''",
            "revoked_from": "VARCHAR(255) DEFAULT ''",
            "revoked_from_scholar_id": "VARCHAR(120) DEFAULT ''",
            "revoked_from_bio_id": "VARCHAR(64) DEFAULT ''",
            "revoked_from_email": "VARCHAR(255) DEFAULT ''",
            "revoked_lab_name": "VARCHAR(255) DEFAULT ''",
        }
    for name, sql_type in types.items():
        if name not in existing:
            sync_conn.execute(text(f"ALTER TABLE inventory_items ADD COLUMN {name} {sql_type}"))


def ensure_inventory_assignments_table(sync_conn) -> None:
    """Create inventory_assignments (M:N) and backfill from legacy item.assigned_scholar_id."""
    from sqlalchemy import inspect, text

    insp = inspect(sync_conn)
    tables = set(insp.get_table_names())
    if "inventory_items" not in tables:
        return
    dialect = sync_conn.dialect.name
    if "inventory_assignments" not in tables:
        if dialect == "postgresql":
            sync_conn.execute(
                text(
                    """
                    CREATE TABLE inventory_assignments (
                        id UUID PRIMARY KEY,
                        inventory_item_id UUID NOT NULL REFERENCES inventory_items(id) ON DELETE CASCADE,
                        scholar_id UUID NOT NULL REFERENCES scholars(id) ON DELETE CASCADE,
                        status VARCHAR(16) NOT NULL DEFAULT 'active',
                        assigned_at TIMESTAMPTZ,
                        assigned_by VARCHAR(80) DEFAULT '',
                        verify_method VARCHAR(16) DEFAULT '',
                        verify_doc_path VARCHAR(512) DEFAULT '',
                        revoked_at TIMESTAMPTZ,
                        revoked_by VARCHAR(80) DEFAULT '',
                        created_at TIMESTAMPTZ,
                        updated_at TIMESTAMPTZ
                    )
                    """
                )
            )
        else:
            sync_conn.execute(
                text(
                    """
                    CREATE TABLE inventory_assignments (
                        id CHAR(32) NOT NULL PRIMARY KEY,
                        inventory_item_id CHAR(32) NOT NULL,
                        scholar_id CHAR(32) NOT NULL,
                        status VARCHAR(16) NOT NULL DEFAULT 'active',
                        assigned_at DATETIME,
                        assigned_by VARCHAR(80) DEFAULT '',
                        verify_method VARCHAR(16) DEFAULT '',
                        verify_doc_path VARCHAR(512) DEFAULT '',
                        revoked_at DATETIME,
                        revoked_by VARCHAR(80) DEFAULT '',
                        created_at DATETIME,
                        updated_at DATETIME,
                        FOREIGN KEY(inventory_item_id) REFERENCES inventory_items(id) ON DELETE CASCADE,
                        FOREIGN KEY(scholar_id) REFERENCES scholars(id) ON DELETE CASCADE
                    )
                    """
                )
            )
        sync_conn.execute(
            text("CREATE INDEX IF NOT EXISTS ix_inv_assign_item_status ON inventory_assignments (inventory_item_id, status)")
        )
        sync_conn.execute(
            text("CREATE INDEX IF NOT EXISTS ix_inv_assign_scholar_status ON inventory_assignments (scholar_id, status)")
        )
        sync_conn.execute(
            text("CREATE INDEX IF NOT EXISTS ix_inv_assign_item_scholar ON inventory_assignments (inventory_item_id, scholar_id)")
        )

    # Backfill active rows from legacy single-scholar columns (once per item/scholar pair).
    rows = sync_conn.execute(
        text(
            """
            SELECT id, assigned_scholar_id, assigned_at, assigned_by,
                   assign_verify_method, assign_verify_doc_path
            FROM inventory_items
            WHERE assigned_scholar_id IS NOT NULL
              AND (assign_verify_method IS NULL OR assign_verify_method != 'owner')
            """
        )
    ).fetchall()
    for row in rows:
        item_id, scholar_id, assigned_at, assigned_by, method, doc = row
        if not scholar_id:
            continue
        exists = sync_conn.execute(
            text(
                """
                SELECT 1 FROM inventory_assignments
                WHERE inventory_item_id = :item_id AND scholar_id = :scholar_id AND status = 'active'
                LIMIT 1
                """
            ),
            {"item_id": item_id, "scholar_id": scholar_id},
        ).fetchone()
        if exists:
            continue
        from uuid import uuid4

        new_id = uuid4()
        sync_conn.execute(
            text(
                """
                INSERT INTO inventory_assignments (
                    id, inventory_item_id, scholar_id, status,
                    assigned_at, assigned_by, verify_method, verify_doc_path,
                    revoked_at, revoked_by, created_at, updated_at
                ) VALUES (
                    :id, :item_id, :scholar_id, 'active',
                    :assigned_at, :assigned_by, :verify_method, :verify_doc_path,
                    NULL, '', :created_at, :updated_at
                )
                """
            ),
            {
                "id": new_id.hex if dialect != "postgresql" else str(new_id),
                "item_id": item_id,
                "scholar_id": scholar_id,
                "assigned_at": assigned_at,
                "assigned_by": assigned_by or "",
                "verify_method": method or "",
                "verify_doc_path": doc or "",
                "created_at": assigned_at,
                "updated_at": assigned_at,
            },
        )


def ensure_scholar_removal_columns(sync_conn) -> None:
    from sqlalchemy import inspect, text

    insp = inspect(sync_conn)
    if "scholars" not in insp.get_table_names():
        return
    existing = {c["name"] for c in insp.get_columns("scholars")}
    if sync_conn.dialect.name == "postgresql":
        types = {
            "removed_at": "TIMESTAMPTZ",
            "removed_by": "VARCHAR(80)",
            "removal_remark": "TEXT",
        }
    else:
        types = {
            "removed_at": "DATETIME",
            "removed_by": "VARCHAR(80)",
            "removal_remark": "TEXT",
        }
    for name, sql_type in types.items():
        if name not in existing:
            sync_conn.execute(text(f"ALTER TABLE scholars ADD COLUMN {name} {sql_type}"))


def ensure_scholar_inv_verify_doc_column(sync_conn) -> None:
    from sqlalchemy import inspect, text

    insp = inspect(sync_conn)
    if "scholars" not in insp.get_table_names():
        return
    existing = {c["name"] for c in insp.get_columns("scholars")}
    if "inv_verify_doc_path" in existing:
        return
    sync_conn.execute(
        text("ALTER TABLE scholars ADD COLUMN inv_verify_doc_path VARCHAR(512) DEFAULT ''")
    )


def ensure_scholar_bio_approve_columns(sync_conn) -> None:
    from sqlalchemy import inspect, text

    insp = inspect(sync_conn)
    if "scholars" not in insp.get_table_names():
        return
    existing = {c["name"] for c in insp.get_columns("scholars")}
    if sync_conn.dialect.name == "postgresql":
        types = {
            "bio_id": "VARCHAR(64) DEFAULT ''",
            "approved": "BOOLEAN DEFAULT FALSE",
            "approved_at": "TIMESTAMPTZ",
            "no_dues": "BOOLEAN DEFAULT FALSE",
            "no_dues_at": "TIMESTAMPTZ",
            "inventory_assigned_at": "TIMESTAMPTZ",
        }
    else:
        types = {
            "bio_id": "VARCHAR(64) DEFAULT ''",
            "approved": "BOOLEAN DEFAULT 0",
            "approved_at": "DATETIME",
            "no_dues": "BOOLEAN DEFAULT 0",
            "no_dues_at": "DATETIME",
            "inventory_assigned_at": "DATETIME",
        }
    for name, sql_type in types.items():
        if name not in existing:
            sync_conn.execute(text(f"ALTER TABLE scholars ADD COLUMN {name} {sql_type}"))


def ensure_registration_token_last_used(sync_conn) -> None:
    from sqlalchemy import inspect, text

    insp = inspect(sync_conn)
    if "registration_tokens" not in insp.get_table_names():
        return
    existing = {c["name"] for c in insp.get_columns("registration_tokens")}
    if "last_used_at" in existing:
        return
    sql_type = "TIMESTAMPTZ" if sync_conn.dialect.name == "postgresql" else "DATETIME"
    sync_conn.execute(text(f"ALTER TABLE registration_tokens ADD COLUMN last_used_at {sql_type}"))
