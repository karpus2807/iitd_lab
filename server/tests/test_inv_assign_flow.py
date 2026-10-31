"""Inventory assign / revoke with OTP and dashboard."""

from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_inventory_dashboard_and_assign_pdf(client: AsyncClient, auth_headers: dict):
    lab = (
        await client.post(
            "/api/labs",
            headers=auth_headers,
            json={"name": "Inv Assign Lab", "room": "1", "incharge": "Prof Owner", "email": "owner@example.com"},
        )
    ).json()
    inv = await client.post(
        "/api/inventory",
        headers=auth_headers,
        json={
            "ic_no": "IRD/ASSIGN/1",
            "item_name": "Laptop",
            "inventory_type": "Lab",
            "inventory_location": lab["name"],
        },
    )
    assert inv.status_code == 200, inv.text
    scholar = await client.post(
        "/api/scholars",
        headers=auth_headers,
        data={
            "lab_id": str(lab["id"]),
            "full_name": "Inv Student",
            "scholar_id": "INV-STU-1",
            "bio_id": "9",
            "email": "student@example.com",
            "system_required": "false",
            "inventory_kind": "none",
            "require_otp": "false",
        },
    )
    assert scholar.status_code == 200, scholar.text

    dash = await client.get("/api/inventory/dashboard", headers=auth_headers)
    assert dash.status_code == 200
    assert any(x["id"] == lab["id"] for x in dash.json()["labs"])

    hits = await client.get(
        "/api/inventory/assignee-search",
        headers=auth_headers,
        params={"q": "INV-STU"},
    )
    assert hits.status_code == 200
    assert any(h["type"] == "scholar" and h["scholar_id"] == "INV-STU-1" for h in hits.json())

    pdf = b"%PDF-1.4\nassign proof\n%%EOF\n"
    done = await client.post(
        "/api/inventory/assign",
        headers=auth_headers,
        data={
            "item_id": inv.json()["id"],
            "scholar_id": scholar.json()["id"],
            "verify_method": "document",
        },
        files={"document": ("proof.pdf", pdf, "application/pdf")},
    )
    assert done.status_code == 200, done.text
    assert done.json()["pending_otp"] is False
    assert done.json()["item"]["assigned_to"] == "Inv Student"

    assigned = await client.get(
        "/api/inventory/assigned-search",
        headers=auth_headers,
        params={"q": "IRD/ASSIGN"},
    )
    assert assigned.status_code == 200
    assert any(x["ic_no"] == "IRD/ASSIGN/1" for x in assigned.json())


@pytest.mark.asyncio
async def test_inventory_assign_otp_and_revoke(client: AsyncClient, auth_headers: dict, monkeypatch):
    await client.put(
        "/api/admin/smtp",
        headers=auth_headers,
        json={
            "enabled": True,
            "host": "smtp.test.local",
            "port": 587,
            "from_addr": "lab@test.local",
            "password": "p",
        },
    )
    monkeypatch.setattr("app.services.email_otp.send_email", AsyncMock())
    monkeypatch.setattr("app.services.email_otp.generate_code", lambda: "112233")

    lab = (
        await client.post(
            "/api/labs",
            headers=auth_headers,
            json={
                "name": "Revoke Lab",
                "room": "2",
                "incharge": "Dr Owner",
                "email": "labowner@example.com",
            },
        )
    ).json()
    inv = await client.post(
        "/api/inventory",
        headers=auth_headers,
        json={"ic_no": "IRD/REV/1", "item_name": "GPU Box", "inventory_location": lab["name"]},
    )
    scholar = await client.post(
        "/api/scholars",
        headers=auth_headers,
        data={
            "lab_id": str(lab["id"]),
            "full_name": "Revoke Student",
            "scholar_id": "REV-1",
            "email": "revstu@example.com",
            "system_required": "false",
            "inventory_kind": "none",
            "require_otp": "false",
        },
    )
    pending = await client.post(
        "/api/inventory/assign",
        headers=auth_headers,
        data={
            "item_id": inv.json()["id"],
            "scholar_id": scholar.json()["id"],
            "verify_method": "otp",
        },
    )
    assert pending.status_code == 200, pending.text
    assert pending.json()["pending_otp"] is True
    verified = await client.post(
        "/api/inventory/assign/verify-otp",
        headers=auth_headers,
        data={"challenge_id": pending.json()["challenge_id"], "code": "112233"},
    )
    assert verified.status_code == 200, verified.text
    assert verified.json()["item"]["assigned_to"] == "Revoke Student"

    monkeypatch.setattr("app.services.email_otp.generate_code", lambda: "445566")
    rev = await client.post(
        "/api/inventory/revoke",
        headers=auth_headers,
        data={"item_id": inv.json()["id"]},
    )
    assert rev.status_code == 200, rev.text
    assert rev.json()["email"] == "labowner@example.com"
    done = await client.post(
        "/api/inventory/revoke/verify-otp",
        headers=auth_headers,
        data={"challenge_id": rev.json()["challenge_id"], "code": "445566"},
    )
    assert done.status_code == 200, done.text
    assert "Dr Owner" in done.json()["item"]["assigned_to"]
    assert done.json()["item"]["assigned_scholar_id"] is None

    issued = await client.get("/api/inventory/assigned-records", headers=auth_headers)
    assert issued.status_code == 200
    assert not any(x["ic_no"] == "IRD/REV/1" for x in issued.json()["items"])

    revoked = await client.get("/api/inventory/revoked-records", headers=auth_headers)
    assert revoked.status_code == 200
    hit = next(x for x in revoked.json()["items"] if x["ic_no"] == "IRD/REV/1")
    assert "Revoke Student" in hit["revoked_from"]
    assert "Dr Owner" in hit["now_with"]

    # Owner-held items must leave revoke search and reject a second revoke.
    after = await client.get(
        "/api/inventory/assigned-search",
        headers=auth_headers,
        params={"q": "IRD/REV"},
    )
    assert after.status_code == 200
    assert not any(x["ic_no"] == "IRD/REV/1" for x in after.json())

    again = await client.post(
        "/api/inventory/revoke",
        headers=auth_headers,
        data={"item_id": inv.json()["id"]},
    )
    assert again.status_code == 400

    dash = await client.get("/api/inventory/dashboard", headers=auth_headers)
    assert dash.status_code == 200
    lab_row = next(x for x in dash.json()["labs"] if x["id"] == lab["id"])
    assert lab_row["assigned"] == 0


@pytest.mark.asyncio
async def test_inventory_batch_assign_and_multi_revoke(client: AsyncClient, auth_headers: dict, monkeypatch):
    await client.put(
        "/api/admin/smtp",
        headers=auth_headers,
        json={
            "enabled": True,
            "host": "smtp.test.local",
            "port": 587,
            "from_addr": "lab@test.local",
            "password": "p",
        },
    )
    monkeypatch.setattr("app.services.email_otp.send_email", AsyncMock())
    monkeypatch.setattr("app.services.email_otp.generate_code", lambda: "778899")

    lab = (
        await client.post(
            "/api/labs",
            headers=auth_headers,
            json={
                "name": "Batch Lab",
                "room": "3",
                "incharge": "Batch Owner",
                "email": "batchowner@example.com",
            },
        )
    ).json()
    ids = []
    for i in (1, 2, 3):
        inv = await client.post(
            "/api/inventory",
            headers=auth_headers,
            json={
                "ic_no": f"IRD/BATCH/{i}",
                "item_name": f"Batch Item {i}",
                "inventory_location": lab["name"],
            },
        )
        assert inv.status_code == 200, inv.text
        ids.append(inv.json()["id"])
    scholar = await client.post(
        "/api/scholars",
        headers=auth_headers,
        data={
            "lab_id": str(lab["id"]),
            "full_name": "Batch Student",
            "scholar_id": "BATCH-1",
            "email": "batchstu@example.com",
            "system_required": "false",
            "inventory_kind": "none",
            "require_otp": "false",
        },
    )
    assert scholar.status_code == 200, scholar.text

    import json

    pending = await client.post(
        "/api/inventory/assign",
        headers=auth_headers,
        data={
            "item_ids": json.dumps(ids),
            "scholar_id": scholar.json()["id"],
            "verify_method": "otp",
        },
    )
    assert pending.status_code == 200, pending.text
    assert pending.json()["pending_otp"] is True
    assert pending.json()["count"] == 3

    verified = await client.post(
        "/api/inventory/assign/verify-otp",
        headers=auth_headers,
        data={"challenge_id": pending.json()["challenge_id"], "code": "778899"},
    )
    assert verified.status_code == 200, verified.text
    assert verified.json()["count"] == 3

    issued = await client.get(
        "/api/inventory/assigned-records",
        headers=auth_headers,
        params={"q": "IRD/BATCH"},
    )
    assert issued.status_code == 200
    assert issued.json()["total"] >= 3

    hits = await client.get(
        "/api/inventory/assigned-search",
        headers=auth_headers,
        params={"q": "Batch Student"},
    )
    assert hits.status_code == 200
    assert len([x for x in hits.json() if x["ic_no"].startswith("IRD/BATCH/")]) >= 3

    monkeypatch.setattr("app.services.email_otp.generate_code", lambda: "990011")
    rev = await client.post(
        "/api/inventory/revoke",
        headers=auth_headers,
        data={"item_ids": json.dumps(ids)},
    )
    assert rev.status_code == 200, rev.text
    assert rev.json()["count"] == 3
    done = await client.post(
        "/api/inventory/revoke/verify-otp",
        headers=auth_headers,
        data={"challenge_id": rev.json()["challenge_id"], "code": "990011"},
    )
    assert done.status_code == 200, done.text
    assert done.json()["count"] == 3

    revoked = await client.get(
        "/api/inventory/revoked-records",
        headers=auth_headers,
        params={"q": "IRD/BATCH"},
    )
    assert revoked.status_code == 200
    assert revoked.json()["total"] >= 3
