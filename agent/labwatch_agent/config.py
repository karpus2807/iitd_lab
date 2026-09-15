from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib


def _env(name: str, default: str | None = None) -> str | None:
    return os.environ.get(name, default)


@dataclass
class AgentConfig:
    server_url: str = "http://hobbit2.cse.iitd.ac.in"
    registration_token: str = ""
    agent_id: str = ""
    heartbeat_interval: int = 30
    metric_interval: int = 30
    inventory_interval: int = 300
    log_level: str = "INFO"
    tls_verify: bool = True
    tls_ca_file: str = ""
    inventory_id: str = ""
    state_dir: str = ""
    config_path: str = ""

    @property
    def state_file(self) -> Path:
        return Path(self.state_dir) / "state.toml"


def default_paths() -> tuple[Path, Path]:
    if os.name == "nt":
        cfg = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / "LabWatch" / "config.toml"
        state = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / "LabWatch" / "state"
    else:
        cfg = Path("/etc/labwatch-agent/config.toml")
        state = Path("/var/lib/labwatch-agent")
    return cfg, state


def load_config(path: str | None = None) -> AgentConfig:
    cfg_path, state_dir = default_paths()
    if path:
        cfg_path = Path(path)
    elif _env("LABWATCH_CONFIG"):
        cfg_path = Path(_env("LABWATCH_CONFIG"))  # type: ignore[arg-type]
    data: dict = {}
    if cfg_path.exists():
        data = tomllib.loads(cfg_path.read_text(encoding="utf-8"))
    server = data.get("server", {})
    agent = data.get("agent", {})
    tls = data.get("tls", {})
    logging_cfg = data.get("logging", {})
    cfg = AgentConfig(
        server_url=_env("SERVER_URL", server.get("url", "http://hobbit2.cse.iitd.ac.in")) or "http://hobbit2.cse.iitd.ac.in",
        registration_token=_env("REGISTRATION_TOKEN", server.get("registration_token", "")) or "",
        agent_id=_env("AGENT_ID", agent.get("id", "")) or "",
        heartbeat_interval=int(_env("HEARTBEAT_INTERVAL", str(agent.get("heartbeat_interval", 30)))),
        metric_interval=int(_env("METRIC_INTERVAL", str(agent.get("metric_interval", 30)))),
        inventory_interval=int(_env("INVENTORY_INTERVAL", str(agent.get("inventory_interval", 300)))),
        log_level=_env("LOG_LEVEL", logging_cfg.get("level", "INFO")) or "INFO",
        tls_verify=str(_env("TLS_VERIFY", str(tls.get("verify", True)))).lower() not in {"0", "false", "no"},
        tls_ca_file=_env("TLS_CA_FILE", tls.get("ca_file", "")) or "",
        inventory_id=_env("INVENTORY_ID", server.get("inventory_id", "")) or "",
        state_dir=_env("LABWATCH_STATE_DIR", str(state_dir)) or str(state_dir),
        config_path=str(cfg_path),
    )
    try:
        Path(cfg.state_dir).mkdir(parents=True, exist_ok=True)
    except OSError:
        fallback = Path.home() / ".local" / "share" / "labwatch-agent"
        fallback.mkdir(parents=True, exist_ok=True)
        cfg.state_dir = str(fallback)
    return cfg


def normalize_agent_state(state: dict | None) -> dict:
    """Flatten `[agent]` TOML so callers can use state.get("agent_id")."""
    if not state:
        return {}
    nested = state.get("agent")
    flat = {k: v for k, v in state.items() if k != "agent"}
    if isinstance(nested, dict):
        for key, value in nested.items():
            flat.setdefault(key, value)
    return flat


def read_state(cfg: AgentConfig) -> dict:
    if not cfg.state_file.exists():
        return {}
    try:
        raw = tomllib.loads(cfg.state_file.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return normalize_agent_state(raw)


def write_state(cfg: AgentConfig, state: dict) -> None:
    state = normalize_agent_state(state)
    lines = ["# Managed by labwatch-agent. Do not share this file.", "[agent]"]
    for k, v in state.items():
        if isinstance(v, (dict, list)):
            continue
        if isinstance(v, bool):
            lines.append(f"{k} = {'true' if v else 'false'}")
        elif isinstance(v, (int, float)):
            lines.append(f"{k} = {v}")
        else:
            escaped = str(v).replace("\\", "\\\\").replace('"', '\\"')
            lines.append(f'{k} = "{escaped}"')
    cfg.state_file.parent.mkdir(parents=True, exist_ok=True)
    cfg.state_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    try:
        os.chmod(cfg.state_file, 0o600)
    except OSError:
        pass
