"""One-line agent installer hosted on hobbit (hostname, not LAN IP)."""

from __future__ import annotations

import io
import tarfile
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import PlainTextResponse, Response

from app.services.public_url import hostname_server_url
from app.services.updates import repo_dir

router = APIRouter(tags=["install"])


def _script_path() -> Path:
    return repo_dir() / "scripts" / "linux" / "install-agent.sh"


@router.get("/install-agent.sh")
async def install_agent_script(request: Request):
    path = _script_path()
    if not path.is_file():
        return PlainTextResponse("install-agent.sh missing on server\n", status_code=404)
    server = hostname_server_url(request)
    text = path.read_text(encoding="utf-8").replace("__SERVER_URL__", server)
    return PlainTextResponse(
        text,
        media_type="text/x-shellscript; charset=utf-8",
        headers={"Content-Disposition": "inline; filename=install-agent.sh"},
    )


@router.get("/agent-pack.tgz")
async def agent_pack():
    agent = repo_dir() / "agent"
    req = agent / "requirements.txt"
    src = agent / "labwatch_agent"
    if not src.is_dir() or not req.is_file():
        return PlainTextResponse("agent pack missing on server\n", status_code=404)
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        tar.add(src, arcname="labwatch_agent")
        tar.add(req, arcname="requirements.txt")
    buf.seek(0)
    return Response(
        content=buf.getvalue(),
        media_type="application/gzip",
        headers={"Content-Disposition": "attachment; filename=agent-pack.tgz"},
    )
