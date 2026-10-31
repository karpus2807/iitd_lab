"""Apply a server-pushed agent-pack update and restart the local service.

On failure during apply, restores the previous labwatch_agent tree.
After restart, a short watchdog restores the previous tree if the service
does not become active (Linux systemd / Windows scheduled task).

Windows: never overwrite the live labwatch_agent package while this process
is still running (file locks). Stage into labwatch_agent.next and swap after stop.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
import textwrap
from pathlib import Path

logger = logging.getLogger("labwatch.agent")

_VERSION_RE = re.compile(r'__version__\s*=\s*["\']([^"\']+)["\']')
BACKUP_NAME = "labwatch_agent.prev"
NEXT_NAME = "labwatch_agent.next"
TASK_NAME = "LabWatchAgent"


def _is_windows() -> bool:
    return os.name == "nt"


def install_prefix() -> Path:
    """PREFIX where run.py + labwatch_agent/ live (e.g. /opt/labwatch-agent)."""
    return Path(__file__).resolve().parent.parent


def _read_version(init_py: Path) -> str:
    text = init_py.read_text(encoding="utf-8", errors="replace")
    match = _VERSION_RE.search(text)
    return match.group(1) if match else ""


def _copy_tree(src: Path, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    for item in src.iterdir():
        target = dest / item.name
        if item.is_dir():
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(item, target)
        else:
            shutil.copy2(item, target)


def _backup_current(prefix: Path) -> Path | None:
    """Snapshot current package so a failed update can restore it."""
    current = prefix / "labwatch_agent"
    if not current.is_dir():
        return None
    backup = prefix / BACKUP_NAME
    if backup.exists():
        shutil.rmtree(backup)
    shutil.copytree(current, backup)
    return backup


def _restore_backup(prefix: Path, backup: Path | None) -> None:
    if not backup or not backup.is_dir():
        return
    current = prefix / "labwatch_agent"
    if current.exists():
        shutil.rmtree(current)
    shutil.move(str(backup), str(current))
    logger.warning("Restored previous agent package from %s", BACKUP_NAME)


def _venv_python(prefix: Path) -> Path:
    if _is_windows():
        return prefix / "venv" / "Scripts" / "python.exe"
    return prefix / "venv" / "bin" / "python"


def _run_pip(venv_python: Path, args: list[str], *, timeout: int) -> None:
    cmd = [str(venv_python), "-m", "pip", *args]
    try:
        completed = subprocess.run(
            cmd,
            check=False,
            timeout=timeout,
            capture_output=True,
            text=True,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"pip timed out after {timeout}s: {' '.join(args[:6])}") from exc
    if completed.returncode != 0:
        tail = ((completed.stderr or "") + "\n" + (completed.stdout or "")).strip()[-800:]
        raise RuntimeError(f"pip failed ({completed.returncode}): {' '.join(args[:8])}\n{tail}")


def apply_pack(pack_bytes: bytes, *, target_version: str = "") -> str:
    """Extract agent-pack.tgz, install wheels + code into PREFIX. Returns new version.

    Always targets the pack shipped by the server (current release), not a
    step-by-step version ladder. Rolls back package files if install fails.
    """
    prefix = install_prefix()
    if not (prefix / "labwatch_agent").is_dir():
        raise RuntimeError(f"Unexpected install layout under {prefix}")

    backup = _backup_current(prefix)
    next_dir = prefix / NEXT_NAME
    live_replaced = False
    try:
        if next_dir.exists():
            shutil.rmtree(next_dir)

        with tempfile.TemporaryDirectory(prefix="labwatch-upd-") as tmp:
            tmp_path = Path(tmp)
            pack_file = tmp_path / "agent-pack.tgz"
            pack_file.write_bytes(pack_bytes)
            extract = tmp_path / "src"
            extract.mkdir()
            with tarfile.open(pack_file, "r:gz") as tar:
                tar.extractall(extract)

            agent_src = extract / "labwatch_agent"
            req = extract / "requirements.txt"
            wheels = extract / "wheels"
            if not agent_src.is_dir():
                raise RuntimeError("agent-pack.tgz missing labwatch_agent/")
            if not req.is_file():
                raise RuntimeError("agent-pack.tgz missing requirements.txt")
            if not wheels.is_dir() or not any(wheels.glob("*.whl")):
                raise RuntimeError("agent-pack.tgz missing offline wheels/")

            new_version = _read_version(agent_src / "__init__.py") or target_version or "unknown"
            venv_python = _venv_python(prefix)
            if not venv_python.is_file():
                raise RuntimeError(f"venv python missing at {venv_python}")

            find_links = f"--find-links={wheels}"
            _run_pip(
                venv_python,
                ["install", "-q", "--no-index", find_links, "-U", "pip", "setuptools", "wheel"],
                timeout=300,
            )
            _run_pip(
                venv_python,
                ["install", "-q", "--no-index", find_links, "-r", str(req)],
                timeout=600,
            )
            # Optional Linux sqlite fallback — never fail the update if missing.
            optional = extract / "requirements-optional-linux.txt"
            if optional.is_file() and not _is_windows():
                try:
                    _run_pip(
                        venv_python,
                        ["install", "-q", "--no-index", find_links, "-r", str(optional)],
                        timeout=300,
                    )
                except Exception:
                    logger.warning("Optional pysqlite3-binary install skipped during self-update")

            if _is_windows():
                # Stage beside the live package; swap after the process exits.
                _copy_tree(agent_src, next_dir)
                installed = _read_version(next_dir / "__init__.py")
                if not installed:
                    raise RuntimeError("Staged package is missing __version__")
                logger.info(
                    "Windows agent staged to %s (%s); will swap on restart",
                    NEXT_NAME,
                    installed,
                )
                return installed

            _copy_tree(agent_src, prefix / "labwatch_agent")
            live_replaced = True
            installed = _read_version(prefix / "labwatch_agent" / "__init__.py")
            if not installed:
                raise RuntimeError("Updated package is missing __version__")
            logger.info("Agent files updated to %s under %s", installed, prefix)
            return installed
    except Exception:
        if next_dir.exists():
            shutil.rmtree(next_dir, ignore_errors=True)
        if live_replaced:
            _restore_backup(prefix, backup)
        elif backup and backup.is_dir():
            # Live tree untouched (Windows stage path / early failure) — drop unused snapshot.
            shutil.rmtree(backup, ignore_errors=True)
        raise


def schedule_restart() -> None:
    """Restart the agent service after this process exits; rollback if it stays down."""
    prefix = install_prefix()
    backup = prefix / BACKUP_NAME
    if _is_windows():
        _schedule_restart_windows(prefix, backup)
        return
    _schedule_restart_linux(prefix, backup)


def _schedule_restart_linux(prefix: Path, backup: Path) -> None:
    backup_q = str(backup).replace("'", "'\"'\"'")
    prefix_q = str(prefix).replace("'", "'\"'\"'")
    script = textwrap.dedent(
        f"""\
        #!/bin/bash
        set -e
        sleep 2
        systemctl restart labwatch-agent || true
        for i in 1 2 3 4 5 6 7 8; do
          sleep 4
          if systemctl is-active --quiet labwatch-agent; then
            exit 0
          fi
        done
        if [ -d '{backup_q}' ]; then
          echo "labwatch-agent failed to stay up — restoring previous package" >&2
          rm -rf '{prefix_q}/labwatch_agent'
          mv '{backup_q}' '{prefix_q}/labwatch_agent'
          systemctl restart labwatch-agent || true
        fi
        """
    )
    try:
        subprocess.Popen(
            ["bash", "-c", script],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            close_fds=True,
        )
    except Exception as exc:
        logger.warning("Could not schedule systemctl restart/rollback: %s", exc)
        try:
            subprocess.Popen(
                ["systemctl", "restart", "labwatch-agent"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
                close_fds=True,
            )
        except Exception as exc2:
            logger.warning("Could not schedule systemctl restart: %s", exc2)


def _schedule_restart_windows(prefix: Path, backup: Path) -> None:
    """Stop task → swap staged next package → start task → rollback if dead."""
    prefix_ps = str(prefix).replace("'", "''")
    backup_ps = str(backup).replace("'", "''")
    next_ps = str(prefix / NEXT_NAME).replace("'", "''")
    current_ps = str(prefix / "labwatch_agent").replace("'", "''")
    task = TASK_NAME
    # Write a .ps1 file — more reliable than -Command with nested quotes on WinPS 5.1.
    script_path = prefix / "labwatch-apply-update.ps1"
    script = textwrap.dedent(
        f"""\
        $ErrorActionPreference = 'Continue'
        $prefix = '{prefix_ps}'
        $backup = '{backup_ps}'
        $next = '{next_ps}'
        $current = '{current_ps}'
        $task = '{task}'
        $log = Join-Path $prefix 'update-restart.log'
        function Log([string]$m) {{
          $line = (Get-Date -Format o) + ' ' + $m
          Add-Content -LiteralPath $log -Value $line -ErrorAction SilentlyContinue
        }}
        Log 'watchdog start'
        Start-Sleep -Seconds 3
        try {{ Stop-ScheduledTask -TaskName $task -ErrorAction SilentlyContinue }} catch {{}}
        # Wait until our python run.py releases file locks.
        for ($i = 0; $i -lt 30; $i++) {{
          $procs = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
            Where-Object {{ $_.CommandLine -and ($_.CommandLine -like '*LabWatch*run.py*' -or $_.CommandLine -like ('*' + $prefix + '*run.py*')) }})
          if ($procs.Count -eq 0) {{ break }}
          Start-Sleep -Seconds 1
        }}
        Start-Sleep -Seconds 1
        if (Test-Path -LiteralPath $next) {{
          Log 'swapping staged package'
          if (Test-Path -LiteralPath $current) {{
            Remove-Item -LiteralPath $current -Recurse -Force -ErrorAction SilentlyContinue
          }}
          Move-Item -LiteralPath $next -Destination $current -Force
        }} else {{
          Log 'no staged next package — restart only'
        }}
        try {{ Start-ScheduledTask -TaskName $task -ErrorAction Stop; Log 'Start-ScheduledTask ok' }}
        catch {{
          Log ('Start-ScheduledTask failed: ' + $_)
          try {{ schtasks /Run /TN $task | Out-Null }} catch {{ Log ('schtasks failed: ' + $_) }}
        }}
        $ok = $false
        for ($i = 0; $i -lt 12; $i++) {{
          Start-Sleep -Seconds 5
          $t = Get-ScheduledTask -TaskName $task -ErrorAction SilentlyContinue
          $procs = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
            Where-Object {{
              $_.CommandLine -and (
                $_.CommandLine -like '*LabWatch*run.py*' -or
                $_.CommandLine -like ('*' + $prefix + '*run.py*') -or
                $_.CommandLine -like '*\\labwatch-agent\\*run.py*'
              )
            }})
          if (($t -and $t.State -eq 'Running') -or $procs.Count -gt 0) {{ $ok = $true; break }}
        }}
        if (-not $ok -and (Test-Path -LiteralPath $backup)) {{
          Log 'agent did not stay up — restoring previous package'
          if (Test-Path -LiteralPath $current) {{
            Remove-Item -LiteralPath $current -Recurse -Force -ErrorAction SilentlyContinue
          }}
          Move-Item -LiteralPath $backup -Destination $current -Force
          try {{ Stop-ScheduledTask -TaskName $task -ErrorAction SilentlyContinue }} catch {{}}
          Start-Sleep -Seconds 1
          try {{ Start-ScheduledTask -TaskName $task -ErrorAction SilentlyContinue }} catch {{}}
          try {{ schtasks /Run /TN $task | Out-Null }} catch {{}}
        }} else {{
          Log ('watchdog done ok=' + $ok)
          if (Test-Path -LiteralPath $backup) {{
            Remove-Item -LiteralPath $backup -Recurse -Force -ErrorAction SilentlyContinue
          }}
        }}
        """
    )
    try:
        script_path.write_text(script, encoding="utf-8")
    except Exception as exc:
        logger.warning("Could not write Windows update script: %s", exc)
        return

    try:
        flags = 0
        if hasattr(subprocess, "CREATE_NO_WINDOW"):
            flags |= subprocess.CREATE_NO_WINDOW
        if hasattr(subprocess, "DETACHED_PROCESS"):
            flags |= subprocess.DETACHED_PROCESS
        # Avoid close_fds=True on Windows — can prevent the child from surviving.
        subprocess.Popen(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-WindowStyle",
                "Hidden",
                "-File",
                str(script_path),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            creationflags=flags,
            close_fds=False,
        )
        logger.info("Windows update watchdog scheduled (%s)", script_path)
    except Exception as exc:
        logger.warning("Could not schedule Windows task restart/rollback: %s", exc)
