#Requires -RunAsAdministrator
# LabWatch Windows uninstall (ASCII-only).
# Optional: -WipeData to also delete %ProgramData%\LabWatch (machine ID / state).
param(
  [switch]$WipeData
)

$ErrorActionPreference = "Stop"
Write-Host "Uninstalling LabWatch agent..."

$InstallDir = Join-Path $env:ProgramFiles "LabWatch Agent"
$svcExe = Join-Path $InstallDir "LabWatchAgentService.exe"

# Prefer WinSW uninstall; also clear legacy scheduled task.
if (Test-Path -LiteralPath $svcExe) {
  try { & $svcExe stop 2>$null | Out-Null } catch {}
  try { & $svcExe uninstall 2>$null | Out-Null } catch {}
}
try { Stop-Service -Name "LabWatchAgent" -Force -ErrorAction SilentlyContinue } catch {}
try { sc.exe delete LabWatchAgent | Out-Null } catch {}

Stop-ScheduledTask -TaskName "LabWatchAgent" -ErrorAction SilentlyContinue
Unregister-ScheduledTask -TaskName "LabWatchAgent" -Confirm:$false -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force $InstallDir -ErrorAction SilentlyContinue

if ($WipeData) {
  Remove-Item -Recurse -Force (Join-Path $env:ProgramData "LabWatch") -ErrorAction SilentlyContinue
  Write-Host "Removed Program Files agent and ProgramData config/state."
} else {
  Write-Host "Removed Program Files agent. Config/state under $env:ProgramData\LabWatch was kept."
  Write-Host "Wipe those too with: powershell -ExecutionPolicy Bypass -File uninstall.ps1 -WipeData"
}

Write-Host "On the LabWatch website: open the machine -> Remove from LabWatch."
