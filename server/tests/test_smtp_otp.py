"""SMTP admin config + scholar enrol OTP gating."""

from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_smtp_get_put(client: AsyncClient, auth_headers: dict):
    got = await client.get("/api/admin/smtp", headers=auth_headers)
    assert got.status_code == 200
    body = got.json()
    assert "enabled" in body
    assert "password" not in body
    assert "password_set" in body

    saved = await client.put(
        "/api/admin/smtp",
        headers=auth_headers,
        json={
            "enabled": False,
            "host": "smtp.test.local",
            "port": 587,
            "username": "labwatch",
            "password": "secret",
            "from_addr": "labwatch@test.local",
            "starttls": True,
        },
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["host"] == "smtp.test.local"
    assert saved.json()["password_set"] is True


@pytest.mark.asyncio
async def test_enroll_without_otp_still_works(client: AsyncClient, auth_headers: dict):
    lab = (
        await client.post(
            "/api/labs",
            headers=auth_headers,
            json={"name": "OTP Lab", "room": "9"},
        )
    ).json()
    created = await client.post(
        "/api/scholars",
        headers=auth_headers,
        data={
            "lab_id": str(lab["id"]),
            "full_name": "No Otp Person",
            "group_name": "M.Tech",
            "email": "noop@example.com",
            "system_required": "false",
            "inventory_kind": "none",
            "require_otp": "false",
        },
    )
    assert created.status_code == 200, created.text
    assert created.json()["full_name"] == "No Otp Person"
    assert created.json().get("pending_otp") is None


@pytest.mark.asyncio
async def test_enroll_with_inv_requires_email_for_otp(client: AsyncClient, auth_headers: dict):
    lab = (
        await client.post(
            "/api/labs",
            headers=auth_headers,
            json={"name": "OTP Inv Lab", "room": "10"},
        )
    ).json()
    inv = await client.post(
        "/api/inventory",
        headers=auth_headers,
        json={"ic_no": "IRD/OTP/1", "item_name": "Box", "inventory_type": "Lab"},
    )
    assert inv.status_code == 200
    bad = await client.post(
        "/api/scholars",
        headers=auth_headers,
        data={
            "lab_id": str(lab["id"]),
            "full_name": "Needs Email",
            "system_required": "true",
            "inventory_kind": "listed",
            "inventory_item_id": inv.json()["id"],
            "require_otp": "false",
            "email": "",
        },
    )
    assert bad.status_code == 400
    assert "email" in bad.json()["detail"].lower()


@pytest.mark.asyncio
async def test_optional_otp_enroll_and_verify(client: AsyncClient, auth_headers: dict, monkeypatch):
    lab = (
        await client.post(
            "/api/labs",
            headers=auth_headers,
            json={"name": "OTP Optional Lab", "room": "11"},
        )
    ).json()
    await client.put(
        "/api/admin/smtp",
        headers=auth_headers,
        json={
            "enabled": True,
            "host": "smtp.test.local",
            "port": 587,
            "username": "u",
            "password": "p",
            "from_addr": "lab@test.local",
            "starttls": True,
        },
    )
    captured: dict = {}

    async def fake_send(db, *, to, subject, body):  # noqa: ANN001
        captured["to"] = to
        captured["body"] = body

    monkeypatch.setattr("app.services.email_otp.send_email", fake_send)
    monkeypatch.setattr("app.services.email_otp.generate_code", lambda: "123456")

    pending = await client.post(
        "/api/scholars",
        headers=auth_headers,
        data={
            "lab_id": str(lab["id"]),
            "full_name": "Otp Person",
            "email": "otp.person@example.com",
            "system_required": "false",
            "inventory_kind": "none",
            "require_otp": "true",
        },
    )
    assert pending.status_code == 200, pending.text
    body = pending.json()
    assert body["pending_otp"] is True
    assert body["challenge_id"]
    assert captured.get("to") == "otp.person@example.com"

    listed = await client.get("/api/scholars", headers=auth_headers, params={"lab_id": lab["id"]})
    assert listed.status_code == 200
    assert listed.json()["total"] == 0

    verified = await client.post(
        "/api/scholars/verify-otp",
        headers=auth_headers,
        data={"challenge_id": body["challenge_id"], "code": "123456"},
    )
    assert verified.status_code == 200, verified.text
    assert verified.json()["scholar"]["full_name"] == "Otp Person"

    listed2 = await client.get("/api/scholars", headers=auth_headers, params={"lab_id": lab["id"]})
    assert listed2.json()["total"] == 1


@pytest.mark.asyncio
async def test_assign_inventory_otp_compulsory(client: AsyncClient, auth_headers: dict, monkeypatch):
    lab = (
        await client.post(
            "/api/labs",
            headers=auth_headers,
            json={"name": "Assign OTP Lab", "room": "12"},
        )
    ).json()
    scholar = await client.post(
        "/api/scholars",
        headers=auth_headers,
        data={
            "lab_id": str(lab["id"]),
            "full_name": "Has Email",
            "email": "has@example.com",
            "system_required": "false",
            "inventory_kind": "none",
            "require_otp": "false",
        },
    )
    assert scholar.status_code == 200
    inv = await client.post(
        "/api/inventory",
        headers=auth_headers,
        json={"ic_no": "IRD/OTP/ASSIGN", "item_name": "PC", "inventory_type": "Lab"},
    )
    assert inv.status_code == 200
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
    monkeypatch.setattr("app.services.email_otp.generate_code", lambda: "654321")

    pending = await client.post(
        f"/api/scholars/{scholar.json()['id']}/assign-inventory",
        headers=auth_headers,
        data={
            "inventory_kind": "listed",
            "inventory_item_id": inv.json()["id"],
        },
    )
    assert pending.status_code == 200, pending.text
    assert pending.json()["pending_otp"] is True

    done = await client.post(
        "/api/scholars/verify-otp",
        headers=auth_headers,
        data={"challenge_id": pending.json()["challenge_id"], "code": "654321"},
    )
    assert done.status_code == 200, done.text
    assert done.json()["scholar"]["system_required"] is True
    assert done.json()["scholar"]["inventory_label"] == "IRD/OTP/ASSIGN"
