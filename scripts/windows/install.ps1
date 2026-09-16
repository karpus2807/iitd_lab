#Requires -RunAsAdministrator
param(
  [Parameter(Mandatory = $true)][string]$ServerUrl,
  [Parameter(Mandatory = $true)][string]$RegistrationToken,
  [string]$InstallDir = "$env:ProgramFiles\LabWatch Agent",
  [string]$DataDir = "$env:ProgramData\LabWatch"
)

$ErrorActionPreference = "Stop"
Write-Host "Installing LabWatch agent to $InstallDir"

New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
New-Item -ItemType Directory -Force -Path $DataDir | Out-Null
New-Item -ItemType Directory -Force -Path "$DataDir\state" | Out-Null

$repoRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$repoAgent = Join-Path $repoRoot "agent"
if (-not (Test-Path (Join-Path $repoAgent "labwatch_agent"))) {
  throw "Could not find agent sources at $repoAgent"
}
Copy-Item -Recurse -Force (Join-Path $repoAgent "labwatch_agent") $InstallDir
Copy-Item -Force (Join-Path $repoAgent "requirements.txt") $InstallDir
Set-Content -Path (Join-Path $InstallDir "run.py") -Value @"
from labwatch_agent.service import main
if __name__ == '__main__':
    raise SystemExit(main())
"@

$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) { $python = Get-Command py -ErrorAction SilentlyContinue }
if (-not $python) { throw "Python 3.8+ is required. Install from https://www.python.org/downloads/windows/ and re-run." }

& $python.Source -m venv "$InstallDir\venv"
& "$InstallDir\venv\Scripts\python.exe" -m pip install -U pip
& "$InstallDir\venv\Scripts\python.exe" -m pip install -r "$InstallDir\requirements.txt"
$site = & "$InstallDir\venv\Scripts\python.exe" -c "import site; print(site.getsitepackages()[0])"
Set-Content -Path (Join-Path $site "labwatch.pth") -Value $InstallDir

$config = Join-Path $DataDir "config.toml"
if (-not (Test-Path $config)) {
  @"
[server]
url = "$ServerUrl"
registration_token = "$RegistrationToken"

[agent]
heartbeat_interval = 30
metric_interval = 30
inventory_interval = 300

[tls]
verify = true

[logging]
level = "INFO"
"@ | Set-Content -Path $config -Encoding UTF8
  icacls $config /inheritance:r /grant:r "SYSTEM:F" "Administrators:F" | Out-Null
}

$wrapper = Join-Path $InstallDir "labwatch-agent.cmd"
@"
@echo off
set LABWATCH_CONFIG=$config
set LABWATCH_STATE_DIR=$DataDir\state
"$InstallDir\venv\Scripts\python.exe" "$InstallDir\run.py" %*
"@ | Set-Content -Path $wrapper -Encoding ASCII

$action = New-ScheduledTaskAction -Execute "$InstallDir\venv\Scripts\python.exe" -Argument "`"$InstallDir\run.py`" run" -WorkingDirectory $InstallDir
$trigger = New-ScheduledTaskTrigger -AtStartup
$principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -RestartCount 5 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit 0
Register-ScheduledTask -TaskName "LabWatchAgent" -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null
Start-ScheduledTask -TaskName "LabWatchAgent"
Write-Host "Installed. Use scripts\windows\status.ps1 / stop.ps1 / uninstall.ps1"
