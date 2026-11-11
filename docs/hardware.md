# Hardware

Do not invent missing data. Unsupported fields are hidden; missing sensors show Not reported.

| Board | Memory | GPU |
| --- | --- | --- |
| SoC (Jetson, Pi) | Unified / soldered | On-package (nvgpu / tegrastats) |
| PC / server | DIMM map when SMBIOS exists | PCIe + `nvidia-smi` when present |

| Data | Linux | Windows |
| --- | --- | --- |
| CPU | `/proc/cpuinfo`, psutil | `Win32_Processor` |
| RAM usage | psutil | psutil |
| RAM slots | `dmidecode -t memory` | `Win32_PhysicalMemory` |
| NVIDIA GPU | `nvidia-smi`, Jetson sysfs | `nvidia-smi` |
| Other GPU | `lspci` name | `Win32_VideoController` |
| Disks | `lsblk`, `smartctl` | `Win32_DiskDrive` |
| Displays | DRM sysfs EDID (`/sys/class/drm/*/edid`) | Dedicated PS: `WmiMonitor*` (decoded) + registry `Enum\\DISPLAY\\…\\EDID` |
| Board / BIOS | dmidecode, sysfs DMI | CIM |
| Network | psutil | psutil + CIM |

Changes (`RAM_REMOVED`, `GPU_CHANGED`, `DISPLAY_REMOVED`, …) become events. VMs are flagged; virtual DIMM maps are not treated as physical.

**Displays** report manufacturer, serial/service tag, diagonal inches, resolution, refresh, and connector (HDMI/DP/…). Re-collected every inventory cycle (~5 min). Unplug → `DISPLAY_REMOVED` (critical alert).
