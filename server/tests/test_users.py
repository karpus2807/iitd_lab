import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_admin_can_update_password_and_delete_user(client: AsyncClient, auth_headers):
    created = await client.post(
        "/api/admin/users",
        headers=auth_headers,
        json={"username": "op1", "email": "op1@example.com", "password": "oldpass12", "role": "OPERATOR", "full_name": "Op"},
    )
    assert created.status_code == 200, created.text
    user_id = created.json()["id"]

    patched = await client.patch(
        f"/api/admin/users/{user_id}",
        headers=auth_headers,
        json={"username": "operator1", "email": "operator1@example.com", "full_name": "Operator One", "password": "newpass12"},
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["username"] == "operator1"
    assert patched.json()["full_name"] == "Operator One"

    login = await client.post("/api/auth/login", json={"username": "operator1", "password": "newpass12"})
    assert login.status_code == 200, login.text
    token = login.json()["access_token"]

    denied = await client.post(
        "/api/auth/password",
        headers={"Authorization": f"Bearer {token}"},
        json={"current_password": "wrongpass", "new_password": "newerpass"},
    )
    assert denied.status_code == 400

    changed = await client.post(
        "/api/auth/password",
        headers={"Authorization": f"Bearer {token}"},
        json={"current_password": "newpass12", "new_password": "newerpass"},
    )
    assert changed.status_code == 200, changed.text
    again = await client.post("/api/auth/login", json={"username": "operator1", "password": "newerpass"})
    assert again.status_code == 200

    removed = await client.delete(f"/api/admin/users/{user_id}", headers=auth_headers)
    assert removed.status_code == 200
    names = {row["username"] for row in (await client.get("/api/admin/users", headers=auth_headers)).json()}
    assert "operator1" not in names


@pytest.mark.asyncio
async def test_cannot_delete_self(client: AsyncClient, auth_headers):
    me = await client.get("/api/auth/me", headers=auth_headers)
    denied = await client.delete(f"/api/admin/users/{me.json()['id']}", headers=auth_headers)
    assert denied.status_code == 400
