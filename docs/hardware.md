# Hardware

LabWatch does not invent missing data. If firmware or the OS does not expose a field, the UI hides it (or shows Not reported for a sensor that should exist).

**SoC** (Jetson, Pi): soldered / unified RAM, on-package GPU. No DIMM map, no removable GPU slot.

**PC / server:** DIMM slots and PCIe GPUs when SMBIOS / `nvidia-smi` provide them.

| Data | Linux | Windows |
| --- | --- | --- |
| CPU | `/proc/cpuinfo`, psutil | `Win32_Processor` |
| RAM usage | psutil | psutil |
| RAM slots | `dmidecode -t memory` | `Win32_PhysicalMemory` |
| GPU NVIDIA | `nvidia-smi`, Jetson sysfs / tegrastats | `nvidia-smi` |
| Other GPU | `lspci` name only | `Win32_VideoController` |
| Disks | `lsblk`, `smartctl` | `Win32_DiskDrive` |
| Board / BIOS | dmidecode, `/sys/class/dmi` | CIM |
| Network | psutil | psutil + CIM |

Hardware changes (`RAM_REMOVED`, `GPU_CHANGED`, …) are stored as events. Virtual machines are flagged and not treated as physical DIMM maps.
