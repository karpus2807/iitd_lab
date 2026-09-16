import json

import pytest
from httpx import AsyncClient

from app.config import get_settings
from app.services import updates as update_svc


RELEASES = [
    {
        "tag": "v1.1.18",
        "name": "LabWatch 1.1.18",
        "published_at": "2026-09-16T05:20:00Z",
        "html_url": "https://github.com/karpus2807/iitd_lab/releases/tag/v1.1.18",
        "notes": "Jetson GPU/RAM/storage collectors, metrics charts, Linux+Windows hybrid",
        "prerelease": False,
    },
    {
        "tag": "v1.1.17",
        "name": "LabWatch 1.1.17",
        "published_at": "2026-09-15T19:40:00Z",
        "html_url": "https://github.com/karpus2807/iitd_lab/releases/tag/v1.1.17",
        "notes": "Fix enrolled=no status and inventory/metrics 500 on GPU hosts",
        "prerelease": False,
    },
    {
        "tag": "v1.1.16",
        "name": "LabWatch 1.1.16",
        "published_at": "2026-09-15T19:10:00Z",
        "html_url": "https://github.com/karpus2807/iitd_lab/releases/tag/v1.1.16",
        "notes": "Agent log levels in the UI; collector tools; last seen",
        "prerelease": False,
    },
    {
        "tag": "v1.1.15",
        "name": "LabWatch 1.1.15",
        "published_at": "2026-09-15T18:40:00Z",
        "html_url": "https://github.com/karpus2807/iitd_lab/releases/tag/v1.1.15",
        "notes": "Remove hosts from the UI; reinstall keeps machine ID and lab",
        "prerelease": False,
    },
    {
        "tag": "v1.1.14",
        "name": "LabWatch 1.1.14",
        "published_at": "2026-09-15T18:10:00Z",
        "html_url": "https://github.com/karpus2807/iitd_lab/releases/tag/v1.1.14",
        "notes": "Numbered lab picker on install and GUI lab assign",
        "prerelease": False,
    },
    {
        "tag": "v1.1.13",
        "name": "LabWatch 1.1.13",
        "published_at": "2026-09-15T17:20:00Z",
        "html_url": "https://github.com/karpus2807/iitd_lab/releases/tag/v1.1.13",
        "notes": "One-command agent install via hobbit hostname",
        "prerelease": False,
    },
    {
        "tag": "v1.1.12",
        "name": "LabWatch 1.1.12",
        "published_at": "2026-09-15T16:55:00Z",
        "html_url": "https://github.com/karpus2807/iitd_lab/releases/tag/v1.1.12",
        "notes": "Admin-only Labs/Updates, proxy fetch, fewer lab fields",
        "prerelease": False,
    },
    {
        "tag": "v1.1.11",
        "name": "LabWatch 1.1.11",
        "published_at": "2026-09-15T16:40:00Z",
        "html_url": "https://github.com/karpus2807/iitd_lab/releases/tag/v1.1.11",
        "notes": "Same Machines sidebar UI on every page",
        "prerelease": False,
    },
    {
        "tag": "v1.1.10",
        "name": "LabWatch 1.1.10",
        "published_at": "2026-09-15T16:20:00Z",
        "html_url": "https://github.com/karpus2807/iitd_lab/releases/tag/v1.1.10",
        "notes": "Fix login Not Found nginx proxy",
        "prerelease": False,
    },
    {
        "tag": "v1.1.9",
        "name": "LabWatch 1.1.9",
        "published_at": "2026-09-15T16:15:00Z",
        "html_url": "https://github.com/karpus2807/iitd_lab/releases/tag/v1.1.9",
        "notes": "Static login form and lab schema repair",
        "prerelease": False,
    },
    {
        "tag": "v1.1.8",
        "name": "LabWatch 1.1.8",
        "published_at": "2026-09-15T16:00:00Z",
        "html_url": "https://github.com/karpus2807/iitd_lab/releases/tag/v1.1.8",
        "notes": "Fix blank login page",
        "prerelease": False,
    },
    {
        "tag": "v1.1.7",
        "name": "LabWatch 1.1.7",
        "published_at": "2026-09-15T13:00:00Z",
        "html_url": "https://github.com/karpus2807/iitd_lab/releases/tag/v1.1.7",
        "notes": "All lab fields editable and a dedicated Updates page on /",
        "prerelease": False,
    },
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

    async def fake_fetch(limit=None, proxy_user=None, proxy_password=None):
        rows = RELEASES[: limit or 3]
        update_svc.cache_path().parent.mkdir(parents=True, exist_ok=True)
        update_svc.cache_path().write_text(json.dumps({"releases": rows}), encoding="utf-8")
        return rows

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


def test_proxy_url_injects_credentials(monkeypatch):
    monkeypatch.setenv("HTTP_PROXY", "http://10.10.78.21:3128")
    monkeypatch.setenv("HTTPS_PROXY", "")
    get_settings.cache_clear()
    url = update_svc._proxy_url("kerberosid", "p@ss")
    assert "kerberosid" in url
    assert "p%40ss" in url
    assert "10.10.78.21:3128" in url
    assert "p@ss" not in update_svc.redact_secrets(url)
    get_settings.cache_clear()


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
    idle = listed.json()
    assert idle["builds"] == []
    assert idle["needs_fetch"] is True
    assert idle["current"]["tag"] == "v1.1.18"

    denied_apply = await client.post("/api/admin/updates/apply", headers=auth_headers, json={"tag": "v1.1.11"})
    assert denied_apply.status_code == 400

    missing = await client.post("/api/admin/updates/fetch", headers=auth_headers, json={"proxy_user": "", "proxy_password": ""})
    assert missing.status_code == 400

    fetched = await client.post(
        "/api/admin/updates/fetch",
        headers=auth_headers,
        json={"proxy_user": "campusid", "proxy_password": "campuspass"},
    )
    assert fetched.status_code == 200, fetched.text
    body = fetched.json()
    assert len(body["builds"]) == 3
    assert body["latest"]["tag"] == "v1.1.18"
    assert body["current"]["tag"] == "v1.1.18"
    assert body["source"] == "github"
    assert body["builds"][0]["is_latest"] is True
    assert any(b["is_current"] for b in body["builds"])

    apply = await client.post("/api/admin/updates/apply", headers=auth_headers, json={"tag": "v1.1.16"})
    assert apply.status_code == 200, apply.text
    status = apply.json()["status"]
    assert status["tag"] == "v1.1.16"
    assert status["state"] == "queued"
    assert (update_harness / "data" / "update-request.json").is_file()

    rejected = await client.post("/api/admin/updates/apply", headers=auth_headers, json={"tag": "v9.9.9"})
    assert rejected.status_code == 400


@pytest.mark.asyncio
async def test_health_reports_version(client: AsyncClient):
    r = await client.get("/health")
    assert r.status_code == 200
    assert r.json()["version"] == update_svc.current_version()
