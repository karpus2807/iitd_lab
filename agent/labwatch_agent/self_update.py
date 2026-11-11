"""Apply a server-pushed agent-pack update and restart the local service.

Safe update contract (Linux + Windows):
1. Snapshot live package → labwatch_agent.prev
2. Stage new package → labwatch_agent.next (live tree never overwritten while running)
3. Install offline wheels into the existing venv
4. Verify staged package (__version__ + compileall)
5. Schedule an out-of-process watchdog that swaps next→live, restarts the service,
   and restores .prev if the new agent does not stay up

On any apply failure the live tree is untouched, .next/.prev staging is cleaned,
and the current process keeps running (caller must not stop).
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
TASK_NAME = "LabWatchAgent"  # legacy scheduled task name (pre-1.2.12)
SERVICE_NAME = "LabWatchAgent"  # Windows service (WinSW) preferred since 1.2.12
UNIT_NAME = "labwatch-agent"


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
    """Snapshot current package so a failed restart can restore it."""
    current = prefix / "labwatch_agent"
    if not current.is_dir():
        return None
    backup = prefix / BACKUP_NAME
    if backup.exists():
        shutil.rmtree(backup)
    shutil.copytree(current, backup)
    return backup


def _cleanup_staging(prefix: Path, *, keep_backup: bool = False) -> None:
    next_dir = prefix / NEXT_NAME
    if next_dir.exists():
        shutil.rmtree(next_dir, ignore_errors=True)
    if not keep_backup:
        backup = prefix / BACKUP_NAME
        if backup.exists():
            shutil.rmtree(backup, ignore_errors=True)


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


def _verify_staged(venv_python: Path, staged: Path) -> str:
    """Ensure staged package has a version and compiles; returns version string."""
    init_py = staged / "__init__.py"
    if not init_py.is_file():
        raise RuntimeError("Staged package is missing __init__.py")
    installed = _read_version(init_py)
    if not installed:
        raise RuntimeError("Staged package is missing __version__")
    try:
        completed = subprocess.run(
            [str(venv_python), "-m", "compileall", "-q", str(staged)],
            check=False,
            timeout=120,
            capture_output=True,
            text=True,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("compileall timed out on staged package") from exc
    if completed.returncode != 0:
        tail = ((completed.stderr or "") + "\n" + (completed.stdout or "")).strip()[-500:]
        raise RuntimeError(f"Staged package failed compileall:\n{tail}")
    return installed


def apply_pack(pack_bytes: bytes, *, target_version: str = "") -> str:
    """Extract agent-pack.tgz, install wheels, stage new code. Returns new version.

    Live labwatch_agent/ is never replaced here — the restart watchdog swaps
    labwatch_agent.next into place. On failure, staging is discarded and the
    running agent keeps the previous version.
    """
    prefix = install_prefix()
    if not (prefix / "labwatch_agent").is_dir():
        raise RuntimeError(f"Unexpected install layout under {prefix}")

    backup = _backup_current(prefix)
    next_dir = prefix / NEXT_NAME
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

            _copy_tree(agent_src, next_dir)
            installed = _verify_staged(venv_python, next_dir)
            if target_version and installed != target_version.lstrip("v"):
                logger.info(
                    "Staged agent version %s (command target was %s)",
                    installed,
                    target_version,
                )
            # Swap onto the live path NOW while this process still holds old modules
            # in memory. That way even if the restart watchdog is killed with the
            # systemd cgroup, Restart=always still boots the new tree from disk.
            live = prefix / "labwatch_agent"
            failed = prefix / "labwatch_agent.failed"
            if failed.exists():
                shutil.rmtree(failed, ignore_errors=True)
            if live.exists():
                shutil.move(str(live), str(failed))
            shutil.move(str(next_dir), str(live))
            shutil.rmtree(failed, ignore_errors=True)
            logger.info(
                "Agent live tree swapped to %s (backup %s); restart will load it",
                installed,
                BACKUP_NAME,
            )
            return installed
    except Exception:
        _cleanup_staging(prefix, keep_backup=False)
        logger.warning(
            "Self-update apply failed — live agent package left at previous version under %s",
            prefix / "labwatch_agent",
        )
        raise
    finally:
        # Keep .prev only when live swap succeeded (next gone, live present).
        live = prefix / "labwatch_agent"
        if (not live.is_dir() or (prefix / NEXT_NAME).is_dir()) and backup and backup.is_dir():
            shutil.rmtree(backup, ignore_errors=True)


def schedule_restart() -> None:
    """Restart the agent after this process exits; rollback to .prev if it stays down."""
    prefix = install_prefix()
    backup = prefix / BACKUP_NAME
    if _is_windows():
        _schedule_restart_windows(prefix, backup)
        return
    _schedule_restart_linux(prefix, backup)


def _schedule_restart_linux(prefix: Path, backup: Path) -> None:
    """Swap staged package outside the agent cgroup.

    Critical: a plain ``Popen(bash)`` from the agent stays in the systemd unit
    cgroup. ``systemctl stop labwatch-agent`` then kills the watchdog too —
    swap never happens (Windows was fine because DETACHED_PROCESS escapes).
    Launch via ``systemd-run`` (transient unit) so the watchdog survives stop.
    """
    backup_q = str(backup).replace("'", "'\"'\"'")
    prefix_q = str(prefix).replace("'", "'\"'\"'")
    next_q = str(prefix / NEXT_NAME).replace("'", "'\"'\"'")
    current_q = str(prefix / "labwatch_agent").replace("'", "'\"'\"'")
    log_q = str(prefix / "update-restart.log").replace("'", "'\"'\"'")
    unit = UNIT_NAME
    script_path = prefix / "labwatch-apply-update.sh"
    script = textwrap.dedent(
        f"""\
        #!/bin/bash
        set +e
        log() {{ echo "$(date -Is) $*" >> '{log_q}' 2>/dev/null || true; }}
        # NEVER leave the unit stopped — if this script dies after stop, EXIT starts it.
        ensure_start() {{
          systemctl start {unit} >/dev/null 2>&1 || systemctl restart {unit} >/dev/null 2>&1 || true
        }}
        trap ensure_start EXIT
        log "watchdog start"
        sleep 2
        systemctl stop {unit} || true
        # Wait for agent process to release files.
        for i in $(seq 1 45); do
          if ! pgrep -f '{prefix_q}/.*run.py' >/dev/null 2>&1; then
            break
          fi
          sleep 1
        done
        # Prefer already-swapped live tree; still accept leftover .next from older agents.
        if [ -d '{next_q}' ]; then
          log "swapping leftover staged package"
          rm -rf '{current_q}'
          mv '{next_q}' '{current_q}'
        else
          log "live tree already swapped — restart only"
        fi
        ensure_start
        ok=0
        for i in $(seq 1 18); do
          sleep 4
          if systemctl is-active --quiet {unit}; then
            ok=1
            break
          fi
          ensure_start
        done
        if [ "$ok" = "1" ]; then
          log "watchdog done ok=1"
          rm -rf '{backup_q}' 2>/dev/null || true
          trap - EXIT
          exit 0
        fi
        if [ -d '{backup_q}' ]; then
          log "agent did not stay up — restoring previous package"
          rm -rf '{current_q}'
          mv '{backup_q}' '{current_q}'
          rm -rf '{next_q}' 2>/dev/null || true
          ensure_start
          sleep 3
          ensure_start
          log "rollback restart attempted"
        else
          log "watchdog done ok=0 (no backup)"
        fi
        """
    )
    try:
        script_path.write_text(script, encoding="utf-8")
        script_path.chmod(0o755)
    except Exception as exc:
        logger.warning("Could not write Linux update script: %s", exc)
        return

    # Prefer a transient systemd unit so stop of labwatch-agent cannot kill us.
    launched = False
    try:
        completed = subprocess.run(
            [
                "systemd-run",
                "--collect",
                f"--unit=labwatch-apply-{os.getpid()}",
                "--description=LabWatch agent package swap",
                "/bin/bash",
                str(script_path),
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if completed.returncode == 0:
            launched = True
            logger.info("Linux update watchdog via systemd-run (%s)", script_path)
        else:
            logger.warning(
                "systemd-run failed (%s): %s",
                completed.returncode,
                ((completed.stderr or "") + (completed.stdout or ""))[:300],
            )
    except Exception as exc:
        logger.warning("systemd-run unavailable: %s", exc)

    if launched:
        return

    # Last resort: at(1) or detached bash (may still die with the unit cgroup).
    try:
        completed = subprocess.run(
            ["at", "now"],
            input=f"/bin/bash {script_path}\n",
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
        if completed.returncode == 0:
            logger.info("Linux update watchdog scheduled via at(1)")
            return
    except Exception:
        pass
    try:
        subprocess.Popen(
            ["/bin/bash", str(script_path)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            close_fds=True,
        )
        logger.warning(
            "Linux update watchdog started detached only — may be killed with unit; prefer systemd-run"
        )
    except Exception as exc:
        logger.warning("Could not schedule Linux restart/rollback: %s", exc)


def _schedule_restart_windows(prefix: Path, backup: Path) -> None:
    """Stop service/task → swap staged next package → start service → rollback if dead."""
    prefix_ps = str(prefix).replace("'", "''")
    backup_ps = str(backup).replace("'", "''")
    next_ps = str(prefix / NEXT_NAME).replace("'", "''")
    current_ps = str(prefix / "labwatch_agent").replace("'", "''")
    svc = SERVICE_NAME
    task = TASK_NAME
    script_path = prefix / "labwatch-apply-update.ps1"
    script = textwrap.dedent(
        f"""\
        $ErrorActionPreference = 'Continue'
        $prefix = '{prefix_ps}'
        $backup = '{backup_ps}'
        $next = '{next_ps}'
        $current = '{current_ps}'
        $svc = '{svc}'
        $task = '{task}'
        $svcExe = Join-Path $prefix 'LabWatchAgentService.exe'
        $log = Join-Path $prefix 'update-restart.log'
        function Log([string]$m) {{
          $line = (Get-Date -Format o) + ' ' + $m
          Add-Content -LiteralPath $log -Value $line -ErrorAction SilentlyContinue
        }}
        function Has-Service {{
          return [bool](Get-Service -Name $svc -ErrorAction SilentlyContinue)
        }}
        function Stop-Agent {{
          if (Has-Service) {{
            try {{ Stop-Service -Name $svc -Force -ErrorAction Stop; Log 'Stop-Service ok'; return }}
            catch {{ Log ('Stop-Service failed: ' + $_) }}
            try {{ if (Test-Path -LiteralPath $svcExe) {{ & $svcExe stop 2>$null | Out-Null; Log 'winsw stop' }} }} catch {{}}
            try {{ sc.exe stop $svc | Out-Null }} catch {{}}
          }}
          try {{ Stop-ScheduledTask -TaskName $task -ErrorAction SilentlyContinue }} catch {{}}
        }}
        function Start-Agent {{
          if (Has-Service) {{
            try {{ Start-Service -Name $svc -ErrorAction Stop; Log 'Start-Service ok'; return $true }}
            catch {{ Log ('Start-Service failed: ' + $_) }}
            try {{
              if (Test-Path -LiteralPath $svcExe) {{
                & $svcExe start 2>$null | Out-Null
                Log 'winsw start'
                return $true
              }}
            }} catch {{ Log ('winsw start failed: ' + $_) }}
            try {{ sc.exe start $svc | Out-Null; Log 'sc start'; return $true }} catch {{ Log ('sc start failed: ' + $_) }}
          }}
          try {{ Start-ScheduledTask -TaskName $task -ErrorAction Stop; Log 'Start-ScheduledTask ok'; return $true }}
          catch {{
            Log ('Start-ScheduledTask failed: ' + $_)
            try {{ schtasks /Run /TN $task | Out-Null; Log 'schtasks /Run ok'; return $true }}
            catch {{ Log ('schtasks failed: ' + $_); return $false }}
          }}
        }}
        function Agent-Procs {{
          return @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
            Where-Object {{
              $_.CommandLine -and (
                $_.CommandLine -like '*LabWatch*run.py*' -or
                $_.CommandLine -like ('*' + $prefix + '*run.py*') -or
                $_.CommandLine -like '*\\labwatch-agent\\*run.py*' -or
                $_.CommandLine -like '*LabWatch Agent*run.py*' -or
                ($_.Name -match 'python' -and $_.CommandLine -like ('*' + $prefix + '*'))
              )
            }})
        }}
        function Agent-Alive {{
          $s = Get-Service -Name $svc -ErrorAction SilentlyContinue
          if ($s -and $s.Status -eq 'Running') {{ return $true }}
          $t = Get-ScheduledTask -TaskName $task -ErrorAction SilentlyContinue
          $procs = Agent-Procs
          return (($t -and $t.State -eq 'Running') -or $procs.Count -gt 0)
        }}
        function Start-AgentDirect {{
          # Last resort if the service/task will not launch.
          $py = Join-Path $prefix 'venv\\Scripts\\python.exe'
          $run = Join-Path $prefix 'run.py'
          if (-not (Test-Path -LiteralPath $py) -or -not (Test-Path -LiteralPath $run)) {{
            Log 'direct start skipped — python/run.py missing'
            return
          }}
          try {{
            Start-Process -FilePath $py -ArgumentList @($run, 'run') -WorkingDirectory $prefix -WindowStyle Hidden
            Log 'direct Start-Process run.py launched'
          }} catch {{
            Log ('direct start failed: ' + $_)
          }}
        }}
        Log 'watchdog start'
        Start-Sleep -Seconds 3
        Stop-Agent
        for ($i = 0; $i -lt 45; $i++) {{
          $procs = Agent-Procs
          if ($procs.Count -eq 0) {{ break }}
          Start-Sleep -Seconds 1
        }}
        Start-Sleep -Seconds 2
        if (Test-Path -LiteralPath $next) {{
          Log 'swapping staged package'
          if (Test-Path -LiteralPath $current) {{
            Remove-Item -LiteralPath $current -Recurse -Force -ErrorAction SilentlyContinue
          }}
          Move-Item -LiteralPath $next -Destination $current -Force
        }} else {{
          Log 'no staged next package — restart only'
        }}
        [void](Start-Agent)
        $ok = $false
        for ($i = 0; $i -lt 18; $i++) {{
          Start-Sleep -Seconds 5
          if (Agent-Alive) {{ $ok = $true; break }}
          if (($i % 3) -eq 2) {{
            Log ('retry Start-Agent loop=' + $i)
            [void](Start-Agent)
          }}
        }}
        if (-not $ok) {{
          Log 'service/task did not stay up — trying direct python run.py'
          Start-AgentDirect
          Start-Sleep -Seconds 8
          if (Agent-Alive) {{ $ok = $true }}
        }}
        if (-not $ok -and (Test-Path -LiteralPath $backup)) {{
          Log 'agent did not stay up — restoring previous package'
          if (Test-Path -LiteralPath $current) {{
            Remove-Item -LiteralPath $current -Recurse -Force -ErrorAction SilentlyContinue
          }}
          Move-Item -LiteralPath $backup -Destination $current -Force
          if (Test-Path -LiteralPath $next) {{
            Remove-Item -LiteralPath $next -Recurse -Force -ErrorAction SilentlyContinue
          }}
          Stop-Agent
          Start-Sleep -Seconds 1
          [void](Start-Agent)
          Start-Sleep -Seconds 3
          [void](Start-Agent)
          Start-Sleep -Seconds 5
          if (-not (Agent-Alive)) {{ Start-AgentDirect }}
          Log 'rollback restart attempted'
        }} else {{
          Log ('watchdog done ok=' + $ok)
          if ($ok -and (Test-Path -LiteralPath $backup)) {{
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
