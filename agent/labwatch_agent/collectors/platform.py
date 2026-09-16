from __future__ import annotations

import os
import platform

from labwatch_agent.util import read_text


def device_tree_text(name: str) -> str | None:
    for path in (f"/proc/device-tree/{name}", f"/sys/firmware/devicetree/base/{name}"):
        value = read_text(path)
        if value:
            return value
    return None


def board_model() -> str | None:
    return device_tree_text("model")


def is_soc_board() -> bool:
    """True for Jetson / Pi / similar soldered-memory boards, not ARM servers with DIMMs."""
    if os.path.exists("/etc/nv_tegra_release") or os.path.exists("/sys/module/tegra_fuse"):
        return True
    model = (board_model() or "").lower()
    if any(token in model for token in ("jetson", "orin", "tegra", "raspberry pi", "raspberrypi", "rockchip", "radxa")):
        return True
    machine = platform.machine().lower()
    if machine in {"aarch64", "arm64", "armv7l", "armv8l"} and board_model() and not os.path.isdir("/sys/class/dmi/id"):
        return True
    return False


def is_jetson() -> bool:
    model = (board_model() or "").lower()
    return bool(
        os.path.exists("/etc/nv_tegra_release")
        or os.path.exists("/sys/module/tegra_fuse")
        or "jetson" in model
        or "orin" in model
        or "tegra" in model
    )
