from __future__ import annotations

import re

_SKIP_PREFIX = ("loop", "zram", "ram", "sr", "fd", "nbd", "dm-", "md")
_SKIP_SUBSTR = ("boot", "rpmb", "zram")


def is_physical_disk(name: str | None) -> bool:
    """Keep NVMe / SATA / eMMC user devices; drop zram, loop, boot partitions."""
    raw = (name or "").strip()
    if not raw:
        return False
    n = raw.lower().rsplit("/", 1)[-1]
    if n.startswith(_SKIP_PREFIX):
        return False
    if any(token in n for token in _SKIP_SUBSTR):
        return False
    return bool(re.match(r"^(nvme\d+n\d+|mmcblk\d+|sd[a-z]+|vd[a-z]+|xvd[a-z]+|hd[a-z]+|nvme\d+)$", n))
