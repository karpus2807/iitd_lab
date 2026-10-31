"""Scholar import/export create detailed op reports; clear by age."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_scholar_import_creates_detailed_report(client: AsyncClient, auth_headers: dict):
    lab = (
        await client.post(
            "/api/labs",
            headers=auth_headers,
            json={"name": "Report Lab", "room": "R1"},
        )
    ).json()

    # Minimal CSV matching scholar template headers
    csv = (
        "Lab Name,Bio-ID,Name,ID,Group,Faculty,System Required,Inventory IC/Label,Email,Phone,No Dues,Notes\n"
        "Report Lab,1,Alice Report,REP-A1,M.Tech,Fac A,No,,a@ex.com,,No,\n"
        "NoSuchLab,2,Bob Missing,REP-B1,M.Tech,Fac B,No,,b@ex.com,,No,\n"
    )
    imp = await client.post(
        "/api/scholars/import",
        headers=auth_headers,
        files={"file": ("scholars.csv", csv.encode("utf-8"), "text/csv")},
    )
    assert imp.status_code == 200, imp.text
    body = imp.json()
    assert body["created"] == 1
    assert body["updated"] == 0
    assert len(body["errors"]) == 1
    assert body.get("report_id")
    report = body["report"]
    assert report["action"] == "import"
    assert len(report["rows"]) == 2
    results = {r["scholar_id"]: r["result"] for r in report["rows"]}
    assert results["REP-A1"] == "created"
    assert results["REP-B1"] == "error"
    assert "unknown lab" in report["rows"][1]["message"].lower() or "unknown lab" in body["errors"][0].lower()

    listed = await client.get("/api/reports?area=scholars&action=import", headers=auth_headers)
    assert listed.status_code == 200
    assert any(x["id"] == body["report_id"] for x in listed.json()["items"])

    detail = await client.get(f"/api/reports/{body['report_id']}", headers=auth_headers)
    assert detail.status_code == 200
    assert detail.json()["summary"]["errors"] == 1

    # lab id used so unused var lint doesn't fire in some runners
    assert lab["id"]


@pytest.mark.asyncio
async def test_reports_clear_all(client: AsyncClient, auth_headers: dict):
    await client.post(
        "/api/labs",
        headers=auth_headers,
        json={"name": "Clear Lab", "room": "C1"},
    )
    csv = (
        "Lab Name,Bio-ID,Name,ID,Group,Faculty,System Required,Inventory IC/Label,Email,Phone,No Dues,Notes\n"
        "Clear Lab,1,Clear Person,CLR-1,M.Tech,,No,,,,No,\n"
    )
    await client.post(
        "/api/scholars/import",
        headers=auth_headers,
        files={"file": ("c.csv", csv.encode("utf-8"), "text/csv")},
    )
    before = await client.get("/api/reports?area=scholars", headers=auth_headers)
    assert before.json()["total"] >= 1

    cleared = await client.post(
        "/api/reports/clear",
        headers=auth_headers,
        json={"older_than_days": 0},
    )
    assert cleared.status_code == 200
    assert cleared.json()["deleted"] >= 1

    after = await client.get("/api/reports?area=scholars", headers=auth_headers)
    assert after.json()["total"] == 0
