import pytest
from httpx import AsyncClient

from app.config import get_settings
from app.services import updates as update_svc


RELEASES = [
    {
        "tag": "v1.1.6",
        "name": "LabWatch 1.1.6",
        "published_at": "2026-09-15T12:30:00Z",
        "html_url": "https://github.com/karpus2807/iitd_lab/releases/tag/v1.1.6",
        "notes": "User edit/delete, labs, and Updates admin pages",
        "prerelease": False,
    },
    {
        "tag": "v1.1.5",
        "name": "LabWatch 1.1.5",
        "published_at": "2026-09-15T12:00:00Z",
        "html_url": "https://github.com/karpus2807/iitd_lab/releases/tag/v1.1.5",
        "notes": "Editable Infra page and Updates UI",
        "prerelease": False,
    },
    {
        "tag": "v1.1.4",
        "name": "LabWatch 1.1.4",
        "published_at": "2026-09-15T11:20:00Z",
        "html_url": "https://github.com/karpus2807/iitd_lab/releases/tag/v1.1.4",
        "notes": "Bind-mount API code",
        "prerelease": False,
    },
]


@pytest.fixture
def update_harness(tmp_path, monkeypatch):
    get_settings.cache_clear()
    monkeypatch.setattr(update_svc, "repo_dir", lambda: tmp_path)
    monkeypatch.setattr(update_svc, "spawn_host_apply", lambda tag: False)

    async def fake_fetch(limit=None):
        return RELEASES[: limit or 3]

    monkeypatch.setattr(update_svc, "fetch_github_releases", fake_fetch)
    (tmp_path / "scripts" / "linux").mkdir(parents=True)
    (tmp_path / "scripts" / "linux" / "apply-requested-update.sh").write_text("#!/bin/sh\n")
    yield tmp_path
    get_settings.cache_clear()


def test_annotate_current_and_latest():
    builds = update_svc.annotate_builds(RELEASES)
    assert builds[0]["is_latest"] is True
    current = next(b for b in builds if b["tag"] == update_svc.current_tag())
    assert current["is_current"] is True
    older = next(b for b in builds if b["tag"] == "v1.1.4")
    assert older["action"] == "downgrade"


@pytest.mark.asyncio
async def test_updates_require_admin(client: AsyncClient, auth_headers, update_harness):
    anon = await client.get("/api/admin/updates")
    assert anon.status_code == 401
    created = await client.post(
        "/api/admin/users",
        headers=auth_headers,
        json={"username": "viewup", "email": "viewup@example.com", "password": "viewerpass", "role": "VIEWER"},
    )
    assert created.status_code == 200
    login = await client.post("/api/auth/login", json={"username": "viewup", "password": "viewerpass"})
    token = login.json()["access_token"]
    denied = await client.get("/api/admin/updates", headers={"Authorization": f"Bearer {token}"})
    assert denied.status_code == 403


@pytest.mark.asyncio
async def test_list_last_three_builds_and_apply(client: AsyncClient, auth_headers, update_harness):
    listed = await client.get("/api/admin/updates", headers=auth_headers)
    assert listed.status_code == 200, listed.text
    body = listed.json()
    assert len(body["builds"]) == 3
    assert body["latest"]["tag"] == "v1.1.6"
    assert body["current"]["tag"] == "v1.1.6"
    assert body["builds"][0]["is_latest"] is True
    assert any(b["is_current"] for b in body["builds"])

    apply = await client.post("/api/admin/updates/apply", headers=auth_headers, json={"tag": "v1.1.5"})
    assert apply.status_code == 200, apply.text
    status = apply.json()["status"]
    assert status["tag"] == "v1.1.5"
    assert status["state"] == "queued"
    assert (update_harness / "data" / "update-request.json").is_file()

    rejected = await client.post("/api/admin/updates/apply", headers=auth_headers, json={"tag": "v9.9.9"})
    assert rejected.status_code == 400


@pytest.mark.asyncio
async def test_health_reports_version(client: AsyncClient):
    r = await client.get("/health")
    assert r.status_code == 200
    assert r.json()["version"] == update_svc.current_version()
