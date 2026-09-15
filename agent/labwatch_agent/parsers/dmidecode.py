from __future__ import annotations

from labwatch_agent.util import dmi_get, parse_dmi_blocks, parse_size_to_bytes


def parse_memory_from_dmidecode(text: str) -> dict:
    blocks = parse_dmi_blocks(text)
    arrays = [b for b in blocks if b.get("_type") == "Physical Memory Array"]
    devices = [b for b in blocks if b.get("_type") == "Memory Device"]

    max_supported = None
    slot_count = None
    notes: list[str] = []
    if arrays:
        max_supported = parse_size_to_bytes(dmi_get(arrays[0], "Maximum Capacity"))
        n = dmi_get(arrays[0], "Number Of Devices")
        if n and n.isdigit():
            slot_count = int(n)
        if len(arrays) > 1:
            # Sum arrays when multiple memory arrays exist.
            total_slots = 0
            total_max = 0
            known_max = True
            for arr in arrays:
                n = dmi_get(arr, "Number Of Devices")
                if n and n.isdigit():
                    total_slots += int(n)
                mx = parse_size_to_bytes(dmi_get(arr, "Maximum Capacity"))
                if mx is None:
                    known_max = False
                else:
                    total_max += mx
            slot_count = total_slots or slot_count
            max_supported = total_max if known_max and total_max else max_supported

    modules = []
    occupied = 0
    for dev in devices:
        locator = dmi_get(dev, "Locator") or dmi_get(dev, "Bank Locator") or f"Device-{len(modules)+1}"
        size_raw = dmi_get(dev, "Size")
        empty = size_raw is None or (size_raw and "no module" in size_raw.lower())
        capacity = None if empty else parse_size_to_bytes(size_raw)
        if not empty and capacity:
            occupied += 1
        speed = dmi_get(dev, "Speed")
        configured = dmi_get(dev, "Configured Memory Speed") or dmi_get(dev, "Configured Clock Speed")
        modules.append(
            {
                "slot_locator": locator,
                "bank_locator": dmi_get(dev, "Bank Locator"),
                "occupied": not empty and capacity is not None,
                "capacity_bytes": capacity,
                "manufacturer": None if empty else dmi_get(dev, "Manufacturer"),
                "part_number": None if empty else dmi_get(dev, "Part Number"),
                "serial_number": None if empty else dmi_get(dev, "Serial Number"),
                "memory_type": None if empty else dmi_get(dev, "Type"),
                "speed_mts": _mhz(speed),
                "configured_speed_mts": _mhz(configured),
                "ecc": None if empty else dmi_get(dev, "Error Correction Type") or dmi_get(dev, "Type Detail"),
                "form_factor": None if empty else dmi_get(dev, "Form Factor"),
                "rank": None if empty else dmi_get(dev, "Rank"),
                "locator_known": bool(dmi_get(dev, "Locator") or dmi_get(dev, "Bank Locator")),
            }
        )

    topology = "UNKNOWN"
    if modules and slot_count:
        topology = "DETECTED"
    elif modules:
        topology = "PARTIAL"
        notes.append("Slot count was not reported by firmware; listing detected memory devices only.")
    else:
        notes.append("Memory topology not exposed by firmware/OS")

    free_slots = None
    unlocated_empty = None
    if slot_count is not None:
        reported_empty = sum(1 for m in modules if not m["occupied"])
        if len(modules) < slot_count:
            unlocated_empty = slot_count - occupied
            notes.append("Firmware did not expose locators for every empty slot.")
            free_slots = slot_count - occupied
        else:
            free_slots = reported_empty if slot_count is not None else None

    occupied_slots = occupied if modules else None
    if slot_count is None and modules:
        # Do not claim this is the physical slot count.
        notes.append("Physical RAM slot count not exposed; occupied module count is from detected devices only.")

    return {
        "max_supported_bytes": max_supported,
        "slot_count": slot_count,
        "occupied_slots": occupied_slots,
        "free_slots": free_slots,
        "unlocated_empty_slots": unlocated_empty,
        "topology_status": topology,
        "modules": modules,
        "notes": notes,
    }


def parse_system_from_dmidecode(text: str) -> dict:
    blocks = parse_dmi_blocks(text)
    system = next((b for b in blocks if b.get("_type") == "System Information"), None)
    board = next((b for b in blocks if b.get("_type") == "Base Board Information"), None)
    bios = next((b for b in blocks if b.get("_type") == "BIOS Information"), None)
    chassis = next((b for b in blocks if b.get("_type") == "Chassis Information"), None)
    return {
        "system_manufacturer": dmi_get(system, "Manufacturer") if system else None,
        "system_model": dmi_get(system, "Product Name") if system else None,
        "system_serial": dmi_get(system, "Serial Number") if system else None,
        "system_uuid": dmi_get(system, "UUID") if system else None,
        "board_manufacturer": dmi_get(board, "Manufacturer") if board else None,
        "board_model": dmi_get(board, "Product Name") if board else None,
        "board_serial": dmi_get(board, "Serial Number") if board else None,
        "board_version": dmi_get(board, "Version") if board else None,
        "bios_vendor": dmi_get(bios, "Vendor") if bios else None,
        "bios_version": dmi_get(bios, "Version") if bios else None,
        "bios_date": dmi_get(bios, "Release Date") if bios else None,
        "chassis_type": dmi_get(chassis, "Type") if chassis else None,
    }


def parse_slots_from_dmidecode(text: str) -> dict:
    blocks = parse_dmi_blocks(text)
    slots = [b for b in blocks if b.get("_type") == "System Slot Information"]
    parsed = []
    notes: list[str] = []
    gpu_capable_known = True
    gpu_total = gpu_occ = 0
    any_gpu_flag = False
    for s in slots:
        designation = dmi_get(s, "Designation") or dmi_get(s, "Slot ID") or f"Slot-{len(parsed)+1}"
        stype = dmi_get(s, "Type")
        usage = dmi_get(s, "Current Usage")
        occupied = None
        if usage:
            occupied = usage.lower() == "in use"
        width = dmi_get(s, "Data Bus Width")
        gen = None
        if stype and "PCI Express" in stype:
            # Generation sometimes encoded in type string, e.g. "PCI Express 4 x16"
            gen = stype
        gpu_capable = None
        blob = " ".join(x.lower() for x in [designation or "", stype or ""] if x)
        if any(k in blob for k in ("gpu", "graphics", "video", "peg", "mxm")):
            gpu_capable = True
            any_gpu_flag = True
        parsed.append(
            {
                "slot_designation": designation,
                "slot_type": stype,
                "generation": gen,
                "width": width,
                "current_usage": usage,
                "occupied": occupied,
                "is_gpu_capable": gpu_capable,
                "attached_device": None,
                "bus_address": dmi_get(s, "Bus Address"),
            }
        )
        if gpu_capable is True:
            gpu_total += 1
            if occupied:
                gpu_occ += 1
        elif gpu_capable is None:
            gpu_capable_known = False

    if not slots:
        return {
            "topology_status": "UNKNOWN",
            "topology_note": "Physical slot topology not exposed by firmware/OS",
            "slots": [],
            "gpu_capable_total": None,
            "gpu_capable_occupied": None,
            "gpu_capable_free": None,
            "notes": ["Do not assume PCIe devices correspond 1:1 with physical slots."],
        }

    gpu_totals = None
    gpu_occupied = None
    gpu_free = None
    if any_gpu_flag:
        gpu_totals = gpu_total
        gpu_occupied = gpu_occ
        gpu_free = gpu_total - gpu_occ
    else:
        notes.append("Firmware did not mark any slot as GPU-capable; PCIe x16 slots are not assumed to be GPU slots.")

    return {
        "topology_status": "DETECTED" if parsed else "UNKNOWN",
        "topology_note": None if parsed else "Physical slot topology not exposed by firmware/OS",
        "slots": parsed,
        "gpu_capable_total": gpu_totals,
        "gpu_capable_occupied": gpu_occupied,
        "gpu_capable_free": gpu_free,
        "notes": notes,
    }


def _mhz(value: str | None) -> int | None:
    if not value:
        return None
    for part in value.replace("MT/s", " ").replace("MHz", " ").split():
        try:
            return int(float(part))
        except ValueError:
            continue
    return None
