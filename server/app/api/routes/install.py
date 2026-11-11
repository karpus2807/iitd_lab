"""One-line agent installer hosted on hobbit (hostname, not LAN IP)."""

from __future__ import annotations

import io
import tarfile
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import PlainTextResponse, Response

from app import __version__ as server_version
from app.config import get_settings
from app.services.agent_pack import agent_pack_version, clear_agent_pack_version_cache
from app.services.public_url import hostname_server_url
from app.services.updates import repo_dir

router = APIRouter(tags=["install"])

# Single source of truth for the portal Install page (no frontend rebuild for notes/versions).
# Bump feature_min / notes here when shipping agent capabilities.
DISPLAY_MONITOR_MIN = "1.2.6"
KEEP_AWAKE_MIN = "1.2.7"  # sleep/hibernate off + NIC/Wi-Fi no power-save
LINUX_UPDATE_FIX_MIN = "1.2.9"  # systemd-run + EXIT trap so stop never leaves agent dead
WINDOWS_SERVICE_MIN = "1.2.12"  # WinSW Windows service (replaces unreliable scheduled task)
REMOTE_UPDATE_MIN = "1.1.40"
SAFE_UPDATE_MIN = "1.2.3"  # stage→swap→rollback self-update


def _linux_script_path() -> Path:
    return repo_dir() / "scripts" / "linux" / "install-agent.sh"


def _windows_script_path() -> Path:
    return repo_dir() / "scripts" / "windows" / "install-agent.ps1"


def _bake_server_url(path: Path, request: Request) -> str:
    server = hostname_server_url(request)
    return path.read_text(encoding="utf-8").replace("__SERVER_URL__", server)


def _install_commands(base: str, github_ps1: str) -> dict:
    return {
        "linux": {
            # --noproxy: campus HTTP_PROXY must not intercept hobbit (returns proxy.cgi HTML).
            "download": (
                f"curl -fsSL --noproxy '*' {base}/install-agent.sh -o /tmp/labwatch-install.sh "
                f"&& head -1 /tmp/labwatch-install.sh | grep -q '^#!'"
            ),
            "install": "sudo bash /tmp/labwatch-install.sh",
            "status": "labwatch-agent status",
            "fix_venv": "sudo rm -rf /opt/labwatch-agent/venv /opt/labwatch-agent/python",
            "restart": "sudo systemctl start labwatch-agent; systemctl is-active labwatch-agent",
            # Multi-line: every privileged step uses sudo (root owns /opt/labwatch-agent).
            "force_update": (
                f"sudo systemctl stop labwatch-agent\n"
                f"curl -fsSL --noproxy '*' {base}/agent-pack.tgz -o /tmp/labwatch-agent-pack.tgz\n"
                f"rm -rf /tmp/labwatch-pack && mkdir -p /tmp/labwatch-pack\n"
                f"tar -xzf /tmp/labwatch-agent-pack.tgz -C /tmp/labwatch-pack\n"
                f"sudo rm -rf /opt/labwatch-agent/labwatch_agent "
                f"/opt/labwatch-agent/labwatch_agent.next /opt/labwatch-agent/labwatch_agent.prev\n"
                f"sudo cp -a /tmp/labwatch-pack/labwatch_agent /opt/labwatch-agent/\n"
                f"sudo systemctl start labwatch-agent\n"
                f"sleep 1\n"
                f"labwatch-agent version\n"
                f"systemctl is-active labwatch-agent"
            ),
            "uninstall_stop": "sudo systemctl disable --now labwatch-agent",
            "uninstall_unit": (
                "sudo rm -f /etc/systemd/system/labwatch-agent.service /usr/local/bin/labwatch-agent"
                " && sudo systemctl daemon-reload"
            ),
            "uninstall_wipe": "sudo rm -rf /opt/labwatch-agent /etc/labwatch-agent /var/lib/labwatch-agent",
        },
        "windows": {
            "clear_installer": "Remove-Item $env:TEMP\\labwatch-install.ps1 -ErrorAction SilentlyContinue",
            "download": f"Invoke-WebRequest -Uri {base}/install-agent.ps1 -OutFile $env:TEMP\\labwatch-install.ps1",
            "install": "powershell -ExecutionPolicy Bypass -File $env:TEMP\\labwatch-install.ps1",
            "status": "Get-Service -Name LabWatchAgent | Format-List Name, Status, StartType",
            "fix_venv": (
                'Remove-Item -Recurse -Force "$env:ProgramFiles\\LabWatch Agent\\venv",'
                '"$env:ProgramFiles\\LabWatch Agent\\python" -ErrorAction SilentlyContinue'
            ),
            "restart_task": (
                'Restart-Service -Name LabWatchAgent -Force; '
                "Get-Service -Name LabWatchAgent | Format-List Name, Status, StartType"
            ),
            "github_download": f"Invoke-WebRequest -Uri {github_ps1} -OutFile $env:TEMP\\labwatch-install.ps1",
            "github_install": (
                "powershell -ExecutionPolicy Bypass -File $env:TEMP\\labwatch-install.ps1 -FromGitHub"
            ),
            "uninstall_task": (
                '$exe = Join-Path $env:ProgramFiles "LabWatch Agent\\LabWatchAgentService.exe"; '
                "if (Test-Path $exe) { & $exe stop; & $exe uninstall }; "
                "Stop-Service LabWatchAgent -Force -ErrorAction SilentlyContinue; "
                "sc.exe delete LabWatchAgent; "
                'Stop-ScheduledTask -TaskName "LabWatchAgent" -ErrorAction SilentlyContinue; '
                'Unregister-ScheduledTask -TaskName "LabWatchAgent" -Confirm:$false -ErrorAction SilentlyContinue'
            ),
            "uninstall_wipe": (
                'Remove-Item -Recurse -Force "$env:ProgramFiles\\LabWatch Agent",'
                '"$env:ProgramData\\LabWatch" -ErrorAction SilentlyContinue'
            ),
        },
    }


@router.get("/api/install/info")
async def install_info(request: Request):
    """Live install metadata for the portal — versions/notes come from the server, not the UI build."""
    clear_agent_pack_version_cache()
    settings = get_settings()
    base = hostname_server_url(request).rstrip("/")
    repo = (settings.github_repo or "karpus2807/iitd_lab").strip()
    github_ps1 = f"https://github.com/{repo}/releases/latest/download/install-agent.ps1"
    agent_ver = agent_pack_version()
    runtime_dir = repo_dir() / "agent" / "python-runtime"
    return {
        "server_url": base,
        "server_version": server_version,
        "agent_version": agent_ver,
        "github_repo": repo,
        "github_install_ps1": github_ps1,
        "requirements": {
            "linux_os": "Ubuntu 16.04+ (or similar glibc hosts)",
            "windows_os": "Windows 10 (1803+) / Windows 11",
            "host_python": "Any (Python 2 / 3.5–3.9 / missing) — left unchanged",
            "agent_python": "LabWatch bundles CPython 3.12 under the agent prefix when host < 3.10",
        },
        "runtimes": {
            "linux_x86_64": (runtime_dir / "linux-x86_64.tgz").is_file(),
            "linux_aarch64": (runtime_dir / "linux-aarch64.tgz").is_file(),
            "windows_x86_64": (runtime_dir / "windows-x86_64.tgz").is_file(),
        },
        "features": [],
        "existing_agents": {
            "need_update_for_displays": True,
            "display_monitor_min": DISPLAY_MONITOR_MIN,
            "keep_awake_min": KEEP_AWAKE_MIN,
            "linux_update_fix_min": LINUX_UPDATE_FIX_MIN,
            "windows_service_min": WINDOWS_SERVICE_MIN,
            "safe_update_min": SAFE_UPDATE_MIN,
            "remote_update_min": REMOTE_UPDATE_MIN,
            "summary": (
                f"Current pack {agent_ver}. Push from Admin → Agents when online "
                f"(remote ≥{REMOTE_UPDATE_MIN}; Linux update fix ≥{LINUX_UPDATE_FIX_MIN}; "
                f"Windows service ≥{WINDOWS_SERVICE_MIN})."
            ),
        },
        "notes": [
            "If download looks like HTML / proxy.cgi Error → use curl --noproxy '*' (campus proxy must not touch hobbit).",
            "get-pip / Python 3.8 error → Clear broken venv, then install again.",
            "Linux offline after update → Start service (or Force-swap).",
            f"Windows: reinstall once (≥{WINDOWS_SERVICE_MIN}) to switch from Task Scheduler to Windows service LabWatchAgent (auto-restart).",
        ],
        "commands": _install_commands(base, github_ps1),
    }


@router.get("/install-agent.sh")
async def install_agent_script(request: Request):
    path = _linux_script_path()
    if not path.is_file():
        return PlainTextResponse("install-agent.sh missing on server\n", status_code=404)
    return PlainTextResponse(
        _bake_server_url(path, request),
        media_type="text/x-shellscript; charset=utf-8",
        headers={"Content-Disposition": "inline; filename=install-agent.sh"},
    )


@router.get("/install-agent.ps1")
async def install_agent_ps1(request: Request):
    path = _windows_script_path()
    if not path.is_file():
        return PlainTextResponse("install-agent.ps1 missing on server\n", status_code=404)
    # UTF-8 BOM so Windows PowerShell 5.1 parses the file as UTF-8 (not ANSI).
    text = "\ufeff" + _bake_server_url(path, request)
    return Response(
        content=text.encode("utf-8"),
        media_type="application/octet-stream",
        headers={"Content-Disposition": "attachment; filename=install-agent.ps1"},
    )


def _add_wheels(tar: tarfile.TarFile, wheels_dir: Path) -> int:
    """Bundle offline pip wheels + get-pip.py into the agent pack."""
    if not wheels_dir.is_dir():
        return 0
    n = 0
    for path in sorted(wheels_dir.iterdir()):
        if path.name.startswith("."):
            continue
        if path.suffix == ".whl" or path.name == "get-pip.py":
            tar.add(path, arcname=f"wheels/{path.name}")
            n += 1
    return n


@router.get("/agent-pack.tgz")
async def agent_pack():
    from app.services.agent_pack import agent_pack_version

    agent = repo_dir() / "agent"
    req = agent / "requirements.txt"
    src = agent / "labwatch_agent"
    wheels = agent / "wheels"
    if not src.is_dir() or not req.is_file():
        return PlainTextResponse("agent pack missing on server\n", status_code=404)
    pack_ver = agent_pack_version()
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        tar.add(src, arcname="labwatch_agent")
        tar.add(req, arcname="requirements.txt")
        optional = agent / "requirements-optional-linux.txt"
        if optional.is_file():
            tar.add(optional, arcname="requirements-optional-linux.txt")
        # WinSW wrapper so Windows agents run as a real service (not Task Scheduler).
        winsw = agent / "vendor" / "winsw" / "WinSW.NET461.exe"
        if winsw.is_file():
            tar.add(winsw, arcname="vendor/winsw/WinSW.NET461.exe")
            winsw_lic = agent / "vendor" / "winsw" / "LICENSE.txt"
            if winsw_lic.is_file():
                tar.add(winsw_lic, arcname="vendor/winsw/LICENSE.txt")
        wheel_count = _add_wheels(tar, wheels)
        if wheel_count == 0:
            # Marker so installers can give a clear error instead of hitting PyPI.
            info = tarfile.TarInfo(name="wheels/.missing")
            payload = b"run scripts/linux/prefetch-agent-wheels.sh on the LabWatch server\n"
            info.size = len(payload)
            tar.addfile(info, io.BytesIO(payload))
    buf.seek(0)
    return Response(
        content=buf.getvalue(),
        media_type="application/gzip",
        headers={
            "Content-Disposition": "attachment; filename=agent-pack.tgz",
            "X-LabWatch-Agent-Version": pack_ver,
        },
    )


@router.get("/python-runtime.tgz")
async def python_runtime(arch: str = "x86_64"):
    """Standalone CPython 3.12 for Linux/Windows agents (host default Python unchanged).

    Prefetch on the server: ``./scripts/linux/prefetch-python-runtime.sh``
    """
    key = (arch or "x86_64").strip().lower().replace("amd64", "x86_64").replace("arm64", "aarch64")
    if key in {"x86_64", "x64", "linux", "linux-x86_64"}:
        fname = "linux-x86_64.tgz"
    elif key in {"aarch64", "arm64", "linux-aarch64"}:
        fname = "linux-aarch64.tgz"
    elif key in {"windows-x86_64", "win_amd64", "win64", "windows", "win"}:
        fname = "windows-x86_64.tgz"
    else:
        return PlainTextResponse(
            f"unsupported arch={arch!r}; use x86_64, aarch64, or windows-x86_64\n",
            status_code=400,
        )
    path = repo_dir() / "agent" / "python-runtime" / fname
    if not path.is_file():
        return PlainTextResponse(
            "python-runtime missing on server — run scripts/linux/prefetch-python-runtime.sh\n",
            status_code=404,
        )
    data = path.read_bytes()
    label = fname.replace(".tgz", "")
    return Response(
        content=data,
        media_type="application/gzip",
        headers={
            "Content-Disposition": f'attachment; filename="{fname}"',
            "X-LabWatch-Python-Runtime-Arch": label,
        },
    )
