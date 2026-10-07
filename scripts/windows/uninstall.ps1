#Requires -RunAsAdministrator
# LabWatch Windows uninstall (ASCII-only).
# Optional: -WipeData to also delete %ProgramData%\LabWatch (machine ID / state).
param(
  [switch]$WipeData
)

$ErrorActionPreference = "Stop"
Write-Host "Uninstalling LabWatch agent..."

Stop-ScheduledTask -TaskName "LabWatchAgent" -ErrorAction SilentlyContinue
Unregister-ScheduledTask -TaskName "LabWatchAgent" -Confirm:$false -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force (Join-Path $env:ProgramFiles "LabWatch Agent") -ErrorAction SilentlyContinue

if ($WipeData) {
  Remove-Item -Recurse -Force (Join-Path $env:ProgramData "LabWatch") -ErrorAction SilentlyContinue
  Write-Host "Removed Program Files agent and ProgramData config/state."
} else {
  Write-Host "Removed Program Files agent. Config/state under $env:ProgramData\LabWatch was kept."
  Write-Host "Wipe those too with: powershell -ExecutionPolicy Bypass -File uninstall.ps1 -WipeData"
}

Write-Host "On the LabWatch website: open the machine -> Remove from LabWatch."
