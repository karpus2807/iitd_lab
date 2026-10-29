"""Asset inventory registry (Inv Management) API."""

import io

import pytest
from httpx import AsyncClient
from openpyxl import Workbook, load_workbook

from app.services.inv_mgmt import EXCEL_HEADERS


async def _create(client: AsyncClient, headers: dict, ic: str, **extra):
    body = {
        "ic_no": ic,
        "item_name": extra.get("item_name", "Workstation"),
        "item_description": extra.get("item_description", "desc"),
        "net_effective_value": extra.get("net_effective_value", 1000.5),
        "inventory_type": extra.get("inventory_type", "Lab"),
        "inventory_location": extra.get("inventory_location", "CLOUD LAB"),
        "gis_date": extra.get("gis_date", "2026-03-14"),
        "inv_type": extra.get("inv_type", "IRD"),
        "remark": extra.get("remark", ""),
    }
    r = await client.post("/api/inventory", headers=headers, json=body)
    assert r.status_code == 200, r.text
    return r.json()


@pytest.mark.asyncio
async def test_crud_remove_and_list(client: AsyncClient, auth_headers: dict):
    a = await _create(client, auth_headers, "IRD/TEST/2026/1")
    listed = await client.get("/api/inventory?status=active&q=IRD/TEST", headers=auth_headers)
    assert listed.status_code == 200
    body = listed.json()
    assert body["total"] >= 1
    assert any(x["ic_no"] == "IRD/TEST/2026/1" for x in body["items"])

    patched = await client.patch(
        f"/api/inventory/{a['id']}",
        headers=auth_headers,
        json={"item_name": "Updated WS", "inventory_location": "ARCH LAB"},
    )
    assert patched.status_code == 200
    assert patched.json()["item_name"] == "Updated WS"

    rem = await client.post(
        "/api/inventory/remove",
        headers=auth_headers,
        json={"ids": [a["id"]], "remark": "Transferred out of lab"},
    )
    assert rem.status_code == 200, rem.text
    assert rem.json()["removed"] == 1

    removed = await client.get("/api/inventory?status=removed&q=IRD/TEST", headers=auth_headers)
    assert removed.status_code == 200
    row = next(x for x in removed.json()["items"] if x["id"] == a["id"])
    assert row["status"] == "removed"
    assert row["removal_remark"] == "Transferred out of lab"
    assert row["removed_by"] == "admin"


@pytest.mark.asyncio
async def test_remove_requires_remark(client: AsyncClient, auth_headers: dict):
    a = await _create(client, auth_headers, "IRD/TEST/2026/2")
    bad = await client.post(
        "/api/inventory/remove",
        headers=auth_headers,
        json={"ids": [a["id"]], "remark": ""},
    )
    assert bad.status_code == 422


@pytest.mark.asyncio
async def test_template_headers_and_import_upsert(client: AsyncClient, auth_headers: dict):
    tmpl = await client.get("/api/inventory/template.xlsx", headers=auth_headers)
    assert tmpl.status_code == 200
    wb = load_workbook(io.BytesIO(tmpl.content), read_only=True)
    headers = [c.value for c in next(wb.active.iter_rows(max_row=1))]
    wb.close()
    assert headers == EXCEL_HEADERS

    out = Workbook()
    ws = out.active
    ws.append(EXCEL_HEADERS)
    ws.append(
        [
            "IRD/IMP/2026/1",
            "GPU Box",
            "Dell tower",
            50000,
            "Lab",
            "VLSI LAB",
            "01-02-2026",
            "Institute",
            "ok",
        ]
    )
    buf = io.BytesIO()
    out.save(buf)
    files = {
        "file": (
            "import.xlsx",
            buf.getvalue(),
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    }
    imp = await client.post("/api/inventory/import", headers=auth_headers, files=files)
    assert imp.status_code == 200, imp.text
    assert imp.json()["created"] == 1

    # Upsert same IC
    out2 = Workbook()
    ws2 = out2.active
    ws2.append(EXCEL_HEADERS)
    ws2.append(
        [
            "IRD/IMP/2026/1",
            "GPU Box v2",
            "Dell tower",
            51000,
            "Lab",
            "VLSI LAB",
            "01-02-2026",
            "Institute",
            "updated",
        ]
    )
    buf2 = io.BytesIO()
    out2.save(buf2)
    imp2 = await client.post(
        "/api/inventory/import",
        headers=auth_headers,
        files={
            "file": (
                "import2.xlsx",
                buf2.getvalue(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )
    assert imp2.status_code == 200
    assert imp2.json()["updated"] == 1

    listed = await client.get("/api/inventory?q=IRD/IMP/2026/1", headers=auth_headers)
    item = next(x for x in listed.json()["items"] if x["ic_no"] == "IRD/IMP/2026/1")
    assert item["item_name"] == "GPU Box v2"
    assert item["remark"] == "updated"


@pytest.mark.asyncio
async def test_suggest_and_batch(client: AsyncClient, auth_headers: dict):
    a = await _create(client, auth_headers, "IRD/SUG/1", item_name="Alpha Kit")
    b = await _create(client, auth_headers, "IRD/SUG/2", item_name="Beta Kit")
    sug = await client.get("/api/inventory/suggest?q=IRD/SUG", headers=auth_headers)
    assert sug.status_code == 200
    assert len(sug.json()) >= 2

    batch = await client.post(
        "/api/inventory/batch",
        headers=auth_headers,
        json={"ids": [a["id"], b["id"]], "fields": {"inventory_location": "BATCH LAB"}},
    )
    assert batch.status_code == 200
    assert batch.json()["updated"] == 2
    listed = await client.get("/api/inventory?q=IRD/SUG", headers=auth_headers)
    locs = {x["ic_no"]: x["inventory_location"] for x in listed.json()["items"] if x["ic_no"].startswith("IRD/SUG")}
    assert locs["IRD/SUG/1"] == "BATCH LAB"
    assert locs["IRD/SUG/2"] == "BATCH LAB"
