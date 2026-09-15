from __future__ import annotations

import argparse
import logging
import os
import random
import signal
import socket
import sys
import time
import uuid
from pathlib import Path

from labwatch_agent import __version__
from labwatch_agent.client import AgentClient
from labwatch_agent.collectors import collect_inventory, collect_metrics
from labwatch_agent.config import AgentConfig, load_config, read_state, write_state
from labwatch_agent.netaddr import collect_host_addresses
from labwatch_agent.queue import EventQueue

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


def _ensure_registered(cfg: AgentConfig, client: AgentClient, state: dict, identity: dict) -> dict:
    if state.get("agent_id") and state.get("agent_secret"):
        client.agent_id = state["agent_id"]
        client.secret = state["agent_secret"]
        return state
    if not cfg.registration_token:
        raise SystemExit("No registration token configured and agent is not enrolled. Set REGISTRATION_TOKEN.")
    logger.info("Registering with %s", cfg.server_url)
    data = client.register(cfg.registration_token, identity, _agent_uuid(cfg, state), __version__)
    state = {
        "agent_id": data["agent_id"],
        "agent_secret": data["agent_secret"],
        "machine_id": data["machine_id"],
        "approved": data.get("approved", True),
    }
    write_state(cfg, state)
    logger.info("Registered machine_id=%s", data["machine_id"])
    return state


def _flush_queue(client: AgentClient, queue: EventQueue) -> None:
    batch = queue.pop_batch(40)
    events = [p for _id, kind, p in batch if kind == "event"]
    logs = [p for _id, kind, p in batch if kind == "log"]
    ids = [i for i, _, _ in batch]
    if events:
        client.events(events)
    if logs:
        client.logs(logs)
    queue.delete(ids)


def run(cfg: AgentConfig) -> int:
    logging.basicConfig(
        level=getattr(logging, cfg.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    if os.name != "nt":
        signal.signal(signal.SIGTERM, _handle_stop)
        signal.signal(signal.SIGINT, _handle_stop)
    else:
        signal.signal(signal.SIGINT, _handle_stop)

    state = read_state(cfg)
    queue = EventQueue(Path(cfg.state_dir) / "queue.db")
    client = AgentClient(cfg, state.get("agent_id", ""), state.get("agent_secret", ""))
    jitter = lambda interval: max(1.0, interval + random.uniform(-0.15, 0.15) * interval)

    last_hb = last_metrics = last_inv = 0.0
    metric_state: dict = {}
    errors: list[str] = []
    identity: dict = {}

    logger.info("LabWatch agent %s starting", __version__)
    while not _STOP:
        now = time.time()
        try:
            if now - last_inv >= jitter(cfg.inventory_interval) or last_inv == 0:
                inventory, errors = collect_inventory(_agent_uuid(cfg, state))
                identity = inventory.get("identity") or {}
                state = _ensure_registered(cfg, client, state, identity)
                client.inventory(inventory)
                last_inv = now
                logger.info("Inventory submitted")
            if now - last_hb >= jitter(cfg.heartbeat_interval):
                addrs = collect_host_addresses()
                client.heartbeat(
                    {
                        "agent_version": __version__,
                        "hostname": identity.get("hostname") if last_inv else socket.gethostname(),
                        "ip_addresses": addrs["ip_addresses"],
                        "mac_addresses": addrs["mac_addresses"],
                        "status": "degraded" if errors else "healthy",
                        "uptime_seconds": time.time() - psutil_boot(),
                        "collector_errors": errors[-10:],
                    }
                )
                last_hb = now
                _flush_queue(client, queue)
            if now - last_metrics >= jitter(cfg.metric_interval):
                metrics, metric_state = collect_metrics(metric_state)
                client.metrics(metrics)
                last_metrics = now
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="labwatch-agent", description="LabWatch monitoring agent")
    parser.add_argument("--config", help="Path to config.toml")
    parser.add_argument("command", nargs="?", default="run", choices=["run", "once", "status", "version"])
    args = parser.parse_args(argv)
    if args.command == "version":
        print(__version__)
        return 0
    cfg = load_config(args.config)
    if args.command == "status":
        state = read_state(cfg)
        print(f"config={cfg.config_path}")
        print(f"server={cfg.server_url}")
        print(f"state_dir={cfg.state_dir}")
        print(f"enrolled={'yes' if state.get('agent_id') else 'no'}")
        print(f"agent_id={state.get('agent_id', '')}")
        print(f"machine_id={state.get('machine_id', '')}")
        return 0
    if args.command == "once":
        state = read_state(cfg)
        inv, errors = collect_inventory(_agent_uuid(cfg, state))
        print("hostname", inv.get("identity", {}).get("hostname"))
        print("cpu", (inv.get("cpu") or {}).get("model"))
        mem = inv.get("memory") or {}
        print("ram_slots", mem.get("slot_count"), "occupied", mem.get("occupied_slots"), "free", mem.get("free_slots"))
        print("gpus", len(inv.get("gpus") or []))
        print("virtual", inv.get("identity", {}).get("is_virtual"))
        print("errors", errors)
        print("notes", inv.get("collection_notes"))
        return 0
    return run(cfg)


if __name__ == "__main__":
    raise SystemExit(main())
