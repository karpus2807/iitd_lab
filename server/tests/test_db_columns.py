from app.db import machine_address_column_sql


def test_postgres_address_columns_use_pg_types():
    pg = machine_address_column_sql("postgresql")
    assert pg["current_ips"] == "JSONB"
    assert pg["ip_changed_at"] == "TIMESTAMPTZ"
    assert "DATETIME" not in pg.values()


def test_sqlite_address_columns_keep_generic_types():
    lite = machine_address_column_sql("sqlite")
    assert lite["current_ips"] == "JSON"
    assert lite["ip_changed_at"] == "DATETIME"
