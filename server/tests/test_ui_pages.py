import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_infra_and_updates_html_pages(client: AsyncClient):
    admin = await client.get("/api/ui/admin")
    assert admin.status_code == 200
    assert "Users" in admin.text
    assert "/api/admin/users" in admin.text

    infra = await client.get("/api/ui/infra")
    assert infra.status_code == 200
    assert "Labs" in infra.text
    assert "/api/labs" in infra.text
    assert "Sign in" in infra.text

    updates = await client.get("/api/ui/updates")
    assert updates.status_code == 200
    assert "Updates" in updates.text
    assert "/api/admin/updates/fetch" in updates.text
    assert "proxy_user" in updates.text

    home = await client.get("/api/ui/app")
    assert home.status_code == 200
    assert 'id="login-form"' in home.text
