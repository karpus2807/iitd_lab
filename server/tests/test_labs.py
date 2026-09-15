import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_seed_only_unassigned_lab(client: AsyncClient, auth_headers):
    labs = await client.get("/api/labs", headers=auth_headers)
    assert labs.status_code == 200
    names = {row["name"] for row in labs.json()}
    assert "Unassigned" in names
    assert "DAIR LAB" not in names


@pytest.mark.asyncio
async def test_lab_crud_and_protect_unassigned(client: AsyncClient, auth_headers):
    created = await client.post(
        "/api/labs",
        headers=auth_headers,
        json={"name": "CSE Lab 1", "building": "Bharti", "room": "201", "description": "UG machines"},
    )
    assert created.status_code == 200, created.text
    body = created.json()
    assert body["name"] == "CSE Lab 1"
    assert body["building"] == "Bharti"
    assert body["protected"] is False
    lab_id = body["id"]

    patched = await client.patch(
        f"/api/labs/{lab_id}",
        headers=auth_headers,
        json={"name": "CSE Hardware Lab", "room": "202"},
    )
    assert patched.status_code == 200
    assert patched.json()["name"] == "CSE Hardware Lab"
    assert patched.json()["room"] == "202"

    labs = await client.get("/api/labs", headers=auth_headers)
    unassigned = next(x for x in labs.json() if x["name"] == "Unassigned")
    denied = await client.delete(f"/api/labs/{unassigned['id']}", headers=auth_headers)
    assert denied.status_code == 400
    renamed = await client.patch(
        f"/api/labs/{unassigned['id']}",
        headers=auth_headers,
        json={"name": "Something else"},
    )
    assert renamed.status_code == 400

    removed = await client.delete(f"/api/labs/{lab_id}", headers=auth_headers)
    assert removed.status_code == 200
    names = {row["name"] for row in (await client.get("/api/labs", headers=auth_headers)).json()}
    assert "CSE Hardware Lab" not in names
