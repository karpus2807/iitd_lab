from __future__ import annotations

import argparse
import logging
import os
import platform
import random
import signal
import socket
import sys
import time
import uuid
from pathlib import Path
from urllib.parse import urlsplit

from labwatch_agent import __version__
from labwatch_agent.client import AgentAuthError, AgentClient
from labwatch_agent.collectors import collect_inventory, collect_metrics
from labwatch_agent.config import AgentConfig, load_config, read_state, write_state
from labwatch_agent.netaddr import collect_host_addresses
from labwatch_agent.queue import EventQueue, QueueLogHandler
from labwatch_agent.self_update import apply_pack, schedule_restart
from labwatch_agent.util import probe_host_tools

logger = logging.getLogger("labwatch.agent")
_STOP = False


def _handle_stop(signum, frame):
    global _STOP
    _STOP = True
    logger.info("Received signal %s, shutting down", signum)


def _agent_uuid(cfg: AgentConfig, state: dict) -> str:
    if cfg.agent_id:
        return cfg.agent_id
    if state.get("agent_id"):
        return str(state["agent_id"])
    return str(uuid.uuid4())


def _fallback_identity() -> dict:
    return {
        "hostname": socket.gethostname(),
        "os_name": platform.system(),
        "architecture": platform.machine(),
        "is_virtual": False,
    }


def _bypass_campus_proxy(server_url: str) -> None:
    host = urlsplit(server_url).hostname or ""
    extra = ",".join(x for x in [host, "localhost", "127.0.0.1"] if x)
    for key in ("NO_PROXY", "no_proxy"):
        current = os.environ.get(key, "")
        parts = [p.strip() for p in current.split(",") if p.strip()]
        for item in extra.split(","):
            if item and item not in parts:
                parts.append(item)
        os.environ[key] = ",".join(parts)
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        os.environ.pop(key, None)


def _ensure_registered(cfg: AgentConfig, client: AgentClient, state: dict, identity: dict) -> dict:
    if state.get("agent_id") and state.get("agent_secret"):
        client.agent_id = state["agent_id"]
        client.secret = state["agent_secret"]
        return state
    if not cfg.registration_token:
        raise SystemExit("No registration token configured and agent is not enrolled. Set REGISTRATION_TOKEN.")
    logger.info("Registering with %s", cfg.server_url)
    data = client.register(cfg.registration_token, identity, _agent_uuid(cfg, state), __version__, cfg.inventory_id)
    state = {
        "agent_id": data["agent_id"],
        "agent_secret": data["agent_secret"],
        "machine_id": data["machine_id"],
        "approved": data.get("approved", True),
    }
    write_state(cfg, state)
    logger.info("Registered machine_id=%s", data["machine_id"])
    return state


def _clear_creds(cfg: AgentConfig, state: dict) -> dict:
    logger.warning("Server rejected agent credentials; will re-register")
    state = {k: v for k, v in state.items() if k not in {"agent_id", "agent_secret"}}
    write_state(cfg, state)
    return state


def _log_collector_note(note: str) -> None:
    text = str(note)
    low = text.lower()
    if any(token in low for token in ("fail", "denied", "missing", "not installed", "unavailable", "error")):
        logger.warning("%s", text)
    else:
        logger.info("%s", text)


def _flush_queue(client: AgentClient, queue: EventQueue) -> None:
    batch = queue.pop_batch(40)
    if not batch:
        return
    events = [p for _id, kind, p in batch if kind == "event"]
    logs = [p for _id, kind, p in batch if kind == "log"]
    ids = [i for i, _, _ in batch]
    if events:
        client.events(events)
    if logs:
        client.logs(logs)
    queue.delete(ids)


def _handle_commands(client: AgentClient, commands: list) -> bool:
    """Process server commands from heartbeat. Returns True if agent should stop (e.g. after update)."""
    global _STOP
    stop = False
    for cmd in commands or []:
        if not isinstance(cmd, dict):
            continue
        if cmd.get("type") != "self_update":
            continue
        cmd_id = str(cmd.get("id") or "")
        if not cmd_id:
            continue
        target = str(cmd.get("target_version") or "")
        pack_path = str(cmd.get("pack_path") or "/agent-pack.tgz")
        logger.info("Self-update command received id=%s target=%s", cmd_id, target or "?")
        try:
            # Already on/above target → ack ok without download/restart (saves bandwidth).
            if target:
                def _vt(v: str) -> tuple[int, int, int]:
                    parts: list[int] = []
                    for piece in (v or "").strip().lstrip("v").split("."):
                        digits = "".join(c for c in piece if c.isdigit())
                        parts.append(int(digits) if digits else 0)
                    while len(parts) < 3:
                        parts.append(0)
                    return parts[0], parts[1], parts[2]

                if _vt(__version__) >= _vt(target):
                    client.ack_command(cmd_id, "ok", f"already at {__version__}", __version__)
                    logger.info("Self-update skipped — already at %s (target %s)", __version__, target)
                    continue
            try:
                client.ack_command(cmd_id, "downloading", f"downloading pack ({target or pack_path})", __version__)
            except Exception:
                pass
            pack = client.download_pack(pack_path)
            try:
                client.ack_command(cmd_id, "applying", f"installing pack ({target or 'latest'})", __version__)
            except Exception:
                pass
            new_ver = apply_pack(pack, target_version=target)
            client.ack_command(cmd_id, "ok", f"updated to {new_ver}", new_ver)
            logger.info("Self-update applied (%s); scheduling restart", new_ver)
            schedule_restart()
            _STOP = True
            stop = True
        except Exception as exc:
            logger.exception("Self-update failed: %s", exc)
            try:
                client.ack_command(cmd_id, "error", str(exc)[:500], __version__)
            except Exception:
                pass
    return stop


def run(cfg: AgentConfig) -> int:
    logging.basicConfig(
        level=getattr(logging, cfg.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    _bypass_campus_proxy(cfg.server_url)
    if os.name != "nt":
        signal.signal(signal.SIGTERM, _handle_stop)
        signal.signal(signal.SIGINT, _handle_stop)
    else:
        signal.signal(signal.SIGINT, _handle_stop)

    state = read_state(cfg)
    queue = EventQueue(Path(cfg.state_dir) / "queue.db")
    ship = QueueLogHandler(queue)
    ship.setLevel(logging.DEBUG)
    lab_log = logging.getLogger("labwatch")
    if not any(isinstance(h, QueueLogHandler) for h in lab_log.handlers):
        lab_log.addHandler(ship)
    lab_log.setLevel(getattr(logging, cfg.log_level.upper(), logging.INFO))
    client = AgentClient(cfg, state.get("agent_id", ""), state.get("agent_secret", ""))
    jitter = lambda interval: max(1.0, interval + random.uniform(-0.15, 0.15) * interval)

    last_hb = last_metrics = last_inv = 0.0
    metric_state: dict = {}
    errors: list[str] = []
    identity: dict = _fallback_identity()
    errors: list[str] = []

    tools = probe_host_tools()
    missing = [name for name, ok in tools.items() if not ok]
    logger.info("LabWatch agent %s starting tools=%s", __version__, tools)
    if missing:
        logger.warning("Missing collector tools (fields will be incomplete): %s", ", ".join(missing))

    while not _STOP:
        now = time.time()
        enrolled = bool(state.get("agent_id") and state.get("agent_secret"))
        try:
            if last_inv == 0 or now - last_inv >= jitter(cfg.inventory_interval) or not enrolled:
                try:
                    inventory, errors = collect_inventory(_agent_uuid(cfg, state))
                    identity = inventory.get("identity") or identity
                    state = _ensure_registered(cfg, client, state, identity)
                    client.inventory(inventory)
                    last_inv = now
                    logger.info("Inventory submitted")
                    for note in inventory.get("collection_notes") or []:
                        _log_collector_note(note)
                    for err in errors:
                        logger.error("%s", err)
                except AgentAuthError:
                    state = _clear_creds(cfg, state)
                    client.agent_id = ""
                    client.secret = ""
                    last_inv = 0
                except Exception as exc:
                    logger.warning("Inventory sync failed: %s", exc)
                    try:
                        if not (state.get("agent_id") and state.get("agent_secret")):
                            state = _ensure_registered(cfg, client, state, identity or _fallback_identity())
                    except Exception as reg_exc:
                        logger.warning("Register failed: %s", reg_exc)

            enrolled = bool(state.get("agent_id") and state.get("agent_secret"))
            if enrolled and now - last_hb >= jitter(cfg.heartbeat_interval):
                try:
                    addrs = collect_host_addresses()
                    hb = client.heartbeat(
                        {
                            "agent_version": __version__,
                            "hostname": identity.get("hostname") or socket.gethostname(),
                            "ip_addresses": addrs["ip_addresses"],
                            "mac_addresses": addrs["mac_addresses"],
                            "status": "degraded" if errors else "healthy",
                            "uptime_seconds": time.time() - psutil_boot(),
                            "collector_errors": errors[-10:],
                        }
                    )
                    last_hb = now
                    if _handle_commands(client, hb.get("commands") or []):
                        break
                except AgentAuthError:
                    state = _clear_creds(cfg, state)
                    client.agent_id = ""
                    client.secret = ""
                    last_inv = 0
                except Exception as exc:
                    logger.warning("Heartbeat failed: %s", exc)
                    queue.push("log", {"level": "WARNING", "message": f"heartbeat failed: {exc}"})
                    client.sleep_backoff()

            if enrolled and now - last_metrics >= jitter(cfg.metric_interval):
                try:
                    metrics, metric_state = collect_metrics(metric_state)
                    client.metrics(metrics)
                    last_metrics = now
                    logger.info("Metrics submitted")
                except AgentAuthError:
                    state = _clear_creds(cfg, state)
                    client.agent_id = ""
                    client.secret = ""
                    last_inv = 0
                except Exception as exc:
                    logger.warning("Metrics sync failed: %s", exc)

            if enrolled:
                try:
                    _flush_queue(client, queue)
                except AgentAuthError:
                    state = _clear_creds(cfg, state)
                    client.agent_id = ""
                    client.secret = ""
                    last_inv = 0
                except Exception as exc:
                    logger.warning("Log ship failed: %s", exc)
        except SystemExit:
            raise
        except Exception as exc:
            logger.warning("Sync failed (%s); buffering and retrying", exc)
            queue.push("log", {"level": "WARNING", "message": f"server unreachable: {exc}"})
            client.sleep_backoff()
        time.sleep(1)
    client.close()
    logger.info("Agent stopped")
    return 0


def psutil_boot() -> float:
    try:
        import psutil

        return psutil.boot_time()
    except Exception:
        return time.time()


def register_once(cfg: AgentConfig) -> int:
    """Login token from installer → register machine + push first inventory (same as Linux first start)."""
    logging.basicConfig(
        level=getattr(logging, cfg.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    _bypass_campus_proxy(cfg.server_url)
    state = read_state(cfg)
    client = AgentClient(cfg, state.get("agent_id", ""), state.get("agent_secret", ""))
    try:
        inventory, errors = collect_inventory(_agent_uuid(cfg, state))
        identity = inventory.get("identity") or _fallback_identity()
        state = _ensure_registered(cfg, client, state, identity)
        client.inventory(inventory)
        print(f"registered machine_id={state.get('machine_id', '')} agent_id={state.get('agent_id', '')}")
        print(f"hostname={identity.get('hostname', '')}")
        for err in errors:
            print(f"collector_error={err}")
        return 0
    except Exception as exc:
        print(f"register_failed={exc}", file=sys.stderr)
        return 1
    finally:
        client.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="labwatch-agent", description="LabWatch monitoring agent")
    parser.add_argument("--config", help="Path to config.toml")
    parser.add_argument("command", nargs="?", default="run", choices=["run", "once", "register", "status", "version"])
    args = parser.parse_args(argv)
    if args.command == "version":
        print(__version__)
        return 0
    cfg = load_config(args.config)
    if args.command == "status":
        state = read_state(cfg)
        tools = probe_host_tools()
        print(f"config={cfg.config_path}")
        print(f"server={cfg.server_url}")
        print(f"state_dir={cfg.state_dir}")
        print(f"enrolled={'yes' if state.get('agent_id') else 'no'}")
        print(f"agent_id={state.get('agent_id', '')}")
        print(f"machine_id={state.get('machine_id', '')}")
        missing = [name for name, ok in tools.items() if not ok]
        print("tools=" + ",".join(f"{k}={'yes' if v else 'no'}" for k, v in tools.items()))
        if missing:
            print("missing_tools=" + ",".join(missing))
        return 0
    if args.command == "register":
        return register_once(cfg)
    if args.command == "once":
        state = read_state(cfg)
        inv, errors = collect_inventory(_agent_uuid(cfg, state))
        print("hostname", inv.get("identity", {}).get("hostname"))
        print("cpu", (inv.get("cpu") or {}).get("model"))
        print("system_uuid", (inv.get("identity") or {}).get("system_uuid"))
        print("motherboard", (inv.get("motherboard") or {}).get("model"))
        mem = inv.get("memory") or {}
        print("ram_slots", mem.get("slot_count"), "occupied", mem.get("occupied_slots"), "free", mem.get("free_slots"))
        print("gpus", len(inv.get("gpus") or []))
        print("disks", len((inv.get("storage") or {}).get("disks") or []))
        print("virtual", inv.get("identity", {}).get("is_virtual"))
        print("tools", probe_host_tools())
        print("errors", errors)
        print("notes", inv.get("collection_notes"))
        return 0
    return run(cfg)


if __name__ == "__main__":
    raise SystemExit(main())
