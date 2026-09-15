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
    assert "Infrastructure" in infra.text
    assert "/api/labs" in infra.text

    updates = await client.get("/api/ui/updates")
    assert updates.status_code == 200
    assert "Server updates" in updates.text
    assert "/api/admin/updates" in updates.text
