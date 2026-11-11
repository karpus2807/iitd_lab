"""Keep lab PCs awake and networking out of power-save so the agent stays reachable.

Best-effort only — never raises into the agent loop. Installers also apply a
stronger one-time OS policy (mask sleep targets / powercfg).
"""

from __future__ import annotations

import logging
import os
import subprocess
from typing import Sequence

logger = logging.getLogger("labwatch.agent")


def _run(args: Sequence[str], timeout: int = 20) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(
            list(args),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return proc.returncode, proc.stdout or "", proc.stderr or ""
    except Exception as exc:
        return 1, "", str(exc)


def _apply_linux() -> list[str]:
    notes: list[str] = []
    # Soft: mask sleep targets (idempotent). Installer does this too.
    for unit in ("sleep.target", "suspend.target", "hibernate.target", "hybrid-sleep.target"):
        code, _, err = _run(["systemctl", "mask", unit], timeout=15)
        if code == 0:
            notes.append(f"masked {unit}")
        elif err and "already" not in err.lower():
            notes.append(f"mask {unit}: {err.strip()[:80]}")

    # NetworkManager: wifi.powersave = 2 (disable). Ignore if NM absent.
    conf_dir = "/etc/NetworkManager/conf.d"
    if os.path.isdir("/etc/NetworkManager"):
        try:
            os.makedirs(conf_dir, exist_ok=True)
            path = os.path.join(conf_dir, "99-labwatch-wifi-powersave.conf")
            desired = "[connection]\nwifi.powersave = 2\n"
            if not os.path.isfile(path) or open(path, encoding="utf-8").read() != desired:
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write(desired)
                _run(["systemctl", "reload", "NetworkManager"], timeout=15)
                notes.append("NM wifi.powersave=2")
        except OSError as exc:
            notes.append(f"NM conf: {exc}")

    # Wi-Fi power_save off on every wireless iface (resets after some driver sleeps).
    try:
        ifaces = sorted(os.listdir("/sys/class/net"))
    except OSError:
        ifaces = []
    for entry in ifaces:
        wireless = f"/sys/class/net/{entry}/wireless"
        if not os.path.isdir(wireless):
            continue
        code, _, err = _run(["iw", "dev", entry, "set", "power_save", "off"], timeout=10)
        if code == 0:
            notes.append(f"wifi power_save off: {entry}")
        else:
            # iw may be missing — try iwconfig
            code2, _, _ = _run(["iwconfig", entry, "power", "off"], timeout=10)
            if code2 == 0:
                notes.append(f"wifi power off (iwconfig): {entry}")
            elif err:
                notes.append(f"wifi {entry}: {(err or 'iw/iwconfig failed')[:80]}")

    # Wired: disable Energy Efficient Ethernet when ethtool supports it.
    for entry in ifaces:
        if entry == "lo" or os.path.isdir(f"/sys/class/net/{entry}/wireless"):
            continue
        code, _, _ = _run(["ethtool", "--set-eee", entry, "eee", "off"], timeout=10)
        if code == 0:
            notes.append(f"eee off: {entry}")
    return notes


def _apply_windows() -> list[str]:
    notes: list[str] = []
    # Never sleep / hibernate on AC or DC.
    cmds = [
        ["powercfg", "/hibernate", "off"],
        ["powercfg", "/change", "standby-timeout-ac", "0"],
        ["powercfg", "/change", "standby-timeout-dc", "0"],
        ["powercfg", "/change", "hibernate-timeout-ac", "0"],
        ["powercfg", "/change", "hibernate-timeout-dc", "0"],
        # Wireless Adapter Settings → Power Saving Mode = Maximum Performance (0)
        [
            "powercfg",
            "/setacvalueindex",
            "SCHEME_CURRENT",
            "19cbb8fa-5279-450e-a69c-8b3fa74bd683",
            "12bbebe6-58d6-4636-95bb-3217ef867c1a",
            "0",
        ],
        [
            "powercfg",
            "/setdcvalueindex",
            "SCHEME_CURRENT",
            "19cbb8fa-5279-450e-a69c-8b3fa74bd683",
            "12bbebe6-58d6-4636-95bb-3217ef867c1a",
            "0",
        ],
        # PCI Express Link State Power Management = Off
        [
            "powercfg",
            "/setacvalueindex",
            "SCHEME_CURRENT",
            "501a4d13-42af-446a-9c2d-43ad520aa2a1",
            "ee12f906-d277-404b-b6da-e5fa1a576df5",
            "0",
        ],
        [
            "powercfg",
            "/setdcvalueindex",
            "SCHEME_CURRENT",
            "501a4d13-42af-446a-9c2d-43ad520aa2a1",
            "ee12f906-d277-404b-b6da-e5fa1a576df5",
            "0",
        ],
        # USB selective suspend = Disabled
        [
            "powercfg",
            "/setacvalueindex",
            "SCHEME_CURRENT",
            "2a737441-1930-4402-8d77-b2bebba308a3",
            "48e6b7a6-50f5-4782-a5d4-53bb8f07e226",
            "0",
        ],
        [
            "powercfg",
            "/setdcvalueindex",
            "SCHEME_CURRENT",
            "2a737441-1930-4402-8d77-b2bebba308a3",
            "48e6b7a6-50f5-4782-a5d4-53bb8f07e226",
            "0",
        ],
        ["powercfg", "/setactive", "SCHEME_CURRENT"],
    ]
    for cmd in cmds:
        code, _, err = _run(cmd, timeout=15)
        if code != 0 and err:
            notes.append(f"{' '.join(cmd[:3])}…: {err.strip()[:60]}")

    # Disable NIC "allow computer to turn off this device".
    ps = r"""
$ErrorActionPreference = 'SilentlyContinue'
Get-NetAdapter -ErrorAction SilentlyContinue | ForEach-Object {
  try { Disable-NetAdapterPowerManagement -Name $_.Name -ErrorAction SilentlyContinue | Out-Null } catch {}
}
'ok'
"""
    code, out, err = _run(
        ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", ps],
        timeout=45,
    )
    if code == 0 and "ok" in (out or ""):
        notes.append("NIC power management disabled")
    elif err:
        notes.append(f"NIC power mgmt: {err.strip()[:80]}")
    return notes


def apply_keep_awake() -> None:
    """Apply sleep/network keep-alive policy. Safe to call on every agent start."""
    try:
        if os.name == "nt":
            notes = _apply_windows()
        elif os.name == "posix":
            notes = _apply_linux()
        else:
            return
        if notes:
            logger.info("Keep-awake applied: %s", "; ".join(notes[:12]))
    except Exception as exc:
        logger.warning("Keep-awake skipped: %s", exc)
