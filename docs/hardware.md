# Hardware detection notes

LabWatch follows a strict rule: **do not invent hardware**.

## Confidence

| Label | Meaning |
| --- | --- |
| DETECTED | Firmware/OS provided a complete enough map (for example all DIMM locators) |
| PARTIAL | Some devices are known but slot counts or empty locators are missing |
| UNKNOWN | The source is absent (no DMI, no WMI array, permission denied) |

UI copy for missing fields is `Unknown / Not reported`.

## Linux sources

| Data | Source |
| --- | --- |
| CPU model/cores | `/proc/cpuinfo`, `psutil` |
| CPU temp | `psutil.sensors_temperatures`, `/sys/class/thermal` |
| RAM usage | `/proc/meminfo` via psutil |
| RAM topology | `dmidecode -t memory` |
| Board/BIOS | `dmidecode` system/baseboard/bios |
| PCIe slots | `dmidecode -t slot` |
| GPU NVIDIA | `nvidia-smi` |
| Other GPUs | `lspci` identity only |
| Disks | `lsblk -J`, optional `smartctl -j` |
| Network | psutil |

Commands are probed with `shutil.which`; a missing binary never crashes the agent.

## Windows sources

| Data | Source |
| --- | --- |
| CPU | `Win32_Processor` |
| RAM modules | `Win32_PhysicalMemory` |
| RAM array / max / slot count | `Win32_PhysicalMemoryArray` |
| Board/BIOS | `Win32_BaseBoard`, `Win32_BIOS`, `Win32_ComputerSystemProduct` |
| GPU identity | `Win32_VideoController` |
| GPU telemetry | `nvidia-smi` when present |
| Disks | `Win32_DiskDrive` |
| Network | `Win32_NetworkAdapter` + psutil |

Windows often omits empty DIMM locators. Occupied modules are listed; free slot count is `MemoryDevices - occupied` when the array is present, with a note that locators for empty slots were not exposed.

## Virtual machines

Hypervisor signatures (KVM, VMware, Hyper-V, VirtualBox, etc.) mark the host as virtual. Do not treat virtual DIMM names as physical motherboard slots for asset audits of lab PCs.

## Diff events

Compared fields are only those present in both snapshots (or a module that disappeared). First-time discovery of a CPU model is not a `CPU_CHANGED` event.
