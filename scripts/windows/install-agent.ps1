#Requires -RunAsAdministrator
# LabWatch one-command Windows installer (served as /install-agent.ps1)
# irm http://hobbit2.cse.iitd.ac.in:8080/install-agent.ps1 | iex
param(
  [string]$ServerUrl = ""
)

$ErrorActionPreference = "Stop"

if (-not $ServerUrl) {
  $ServerUrl = "__SERVER_URL__"
}
if ($ServerUrl -eq "__SERVER_URL__" -or -not $ServerUrl) {
  $ServerUrl = "http://hobbit2.cse.iitd.ac.in:8080"
}
$ServerUrl = $ServerUrl.TrimEnd("/")

$InstallDir = Join-Path $env:ProgramFiles "LabWatch Agent"
$DataDir = Join-Path $env:ProgramData "LabWatch"
$ConfigPath = Join-Path $DataDir "config.toml"
$StateDir = Join-Path $DataDir "state"

function Invoke-LwJson {
  param(
    [string]$Method,
    [string]$Path,
    [hashtable]$Body = $null,
    [string]$Token = ""
  )
  $headers = @{ "Content-Type" = "application/json" }
  if ($Token) { $headers["Authorization"] = "Bearer $Token" }
  $params = @{
    Method = $Method
    Uri = "$ServerUrl$Path"
    Headers = $headers
    UseBasicParsing = $true
  }
  if ($Body) { $params.Body = ($Body | ConvertTo-Json -Compress -Depth 6) }
  try {
    return Invoke-RestMethod @params
  } catch {
    $msg = $_.Exception.Message
    if ($_.ErrorDetails.Message) { $msg = $_.ErrorDetails.Message }
    throw "Request failed ($Method $Path): $msg"
  }
}

Write-Host "LabWatch agent install → $ServerUrl"
Write-Host "Password typing is invisible."

$Username = Read-Host "LabWatch username (admin or operator)"
$Secure = Read-Host "Password" -AsSecureString
$BSTR = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($Secure)
try {
  $Password = [Runtime.InteropServices.Marshal]::PtrToStringAuto($BSTR)
} finally {
  [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($BSTR) | Out-Null
}
if (-not $Username -or -not $Password) { throw "Username and password are required." }

$ExistingId = ""
if (Test-Path $ConfigPath) {
  $m = Select-String -Path $ConfigPath -Pattern '^\s*inventory_id\s*=\s*"?([^"]+)"?' | Select-Object -First 1
  if ($m) { $ExistingId = $m.Matches[0].Groups[1].Value.Trim() }
}
$hint = if ($ExistingId) { $ExistingId } else { "example 12345/2012/12" }
$InventoryId = Read-Host "Machine ID [$hint]"
if (-not $InventoryId) { $InventoryId = $ExistingId }
if (-not $InventoryId) { throw "Machine ID is required." }

Write-Host "Logging in and loading labs…"
$login = Invoke-LwJson -Method POST -Path "/api/auth/login" -Body @{ username = $Username; password = $Password }
$access = $login.access_token
$labs = @(Invoke-LwJson -Method GET -Path "/api/labs" -Token $access)
if ($labs.Count -eq 0) { throw "No labs found. Create labs in Admin first." }
$labs = $labs | Sort-Object { if (("" + $_.name).Trim().ToLower() -eq "unassigned") { 0 } else { 1 } }, name

$currentLab = $null
$listed = Invoke-LwJson -Method GET -Path ("/api/machines?inventory_id=" + [uri]::EscapeDataString($InventoryId)) -Token $access
if ($listed -is [array] -and $listed.Count -gt 0 -and $listed[0].lab_id) {
  $currentLab = $labs | Where-Object { $_.id -eq $listed[0].lab_id } | Select-Object -First 1
}
if (-not $currentLab) {
  $currentLab = $labs | Where-Object { ("" + $_.name).Trim().ToLower() -eq "unassigned" } | Select-Object -First 1
}
if (-not $currentLab) { $currentLab = $labs[0] }

Write-Host ""
Write-Host "Labs:"
for ($i = 0; $i -lt $labs.Count; $i++) {
  $mark = if ($labs[$i].id -eq $currentLab.id) { "  [current]" } else { "" }
  $hosts = if ($null -ne $labs[$i].machine_count) { "  ($($labs[$i].machine_count) hosts)" } else { "" }
  Write-Host ("  {0}) {1}{2}{3}" -f ($i + 1), $labs[$i].name, $hosts, $mark)
}
$choice = Read-Host "Select lab number (Enter keeps $($currentLab.name))"
$lab = $currentLab
if ($choice) {
  $n = 0
  if (-not [int]::TryParse($choice, [ref]$n) -or $n -lt 1 -or $n -gt $labs.Count) {
    throw "Lab number must be between 1 and $($labs.Count)"
  }
  $lab = $labs[$n - 1]
}

Write-Host "Enrolling $InventoryId in $($lab.name)…"
$enroll = Invoke-LwJson -Method POST -Path "/api/agents/enroll" -Body @{
  username = $Username
  password = $Password
  inventory_id = $InventoryId
  lab_id = $lab.id
}
$Password = $null
$Token = $enroll.registration_token
if ($enroll.server_url) { $ServerUrl = ([string]$enroll.server_url).TrimEnd("/") }
if (-not $Token) { throw "Enroll did not return a registration token." }

$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) { $python = Get-Command py -ErrorAction SilentlyContinue }
if (-not $python) {
  throw "Python 3.8+ is required. Install from https://www.python.org/downloads/windows/ (Add to PATH), then re-run."
}

New-Item -ItemType Directory -Force -Path $InstallDir, $DataDir, $StateDir | Out-Null
$work = Join-Path $env:TEMP ("labwatch-agent-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Force -Path $work | Out-Null
try {
  $pack = Join-Path $work "agent-pack.tgz"
  Write-Host "Downloading agent pack…"
  Invoke-WebRequest -Uri "$ServerUrl/agent-pack.tgz" -OutFile $pack -UseBasicParsing
  $src = Join-Path $work "src"
  New-Item -ItemType Directory -Force -Path $src | Out-Null
  tar -xzf $pack -C $src
  if (-not (Test-Path (Join-Path $src "labwatch_agent"))) {
    throw "agent-pack.tgz did not contain labwatch_agent"
  }

  Write-Host "Installing to $InstallDir"
  Get-ScheduledTask -TaskName "LabWatchAgent" -ErrorAction SilentlyContinue | Unregister-ScheduledTask -Confirm:$false -ErrorAction SilentlyContinue

  if (Test-Path (Join-Path $InstallDir "venv")) {
    Remove-Item -Recurse -Force (Join-Path $InstallDir "venv")
  }
  & $python.Source -m venv (Join-Path $InstallDir "venv")
  $py = Join-Path $InstallDir "venv\Scripts\python.exe"
  & $py -m pip install -U pip
  & $py -m pip install -r (Join-Path $src "requirements.txt")
  Copy-Item -Recurse -Force (Join-Path $src "labwatch_agent") $InstallDir
  Set-Content -Path (Join-Path $InstallDir "run.py") -Value @"
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from labwatch_agent.service import main
if __name__ == '__main__':
    raise SystemExit(main())
"@
  $site = & $py -c "import sysconfig; print(sysconfig.get_path('purelib'))"
  Set-Content -Path (Join-Path $site "labwatch.pth") -Value $InstallDir

  $labToml = ($lab.name -replace '\\', '\\' -replace '"', '\"')
  @"
[server]
url = "$ServerUrl"
registration_token = "$Token"
inventory_id = "$InventoryId"
lab_id = "$($lab.id)"
lab = "$labToml"

[agent]
heartbeat_interval = 30
metric_interval = 30
inventory_interval = 300

[tls]
verify = true

[logging]
level = "INFO"
"@ | Set-Content -Path $ConfigPath -Encoding UTF8
  icacls $ConfigPath /inheritance:r /grant:r "SYSTEM:F" "Administrators:F" | Out-Null
  Remove-Item -Force (Join-Path $StateDir "state.toml") -ErrorAction SilentlyContinue

  $wrapper = Join-Path $InstallDir "labwatch-agent.cmd"
  @"
@echo off
set LABWATCH_CONFIG=$ConfigPath
set LABWATCH_STATE_DIR=$StateDir
set PYTHONPATH=$InstallDir
"$py" "$InstallDir\run.py" %*
"@ | Set-Content -Path $wrapper -Encoding ASCII

  $action = New-ScheduledTaskAction -Execute $wrapper -Argument "run" -WorkingDirectory $InstallDir
  $trigger = New-ScheduledTaskTrigger -AtStartup
  $principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
  $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -RestartCount 5 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit 0
  Register-ScheduledTask -TaskName "LabWatchAgent" -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null
  Start-ScheduledTask -TaskName "LabWatchAgent"
  Write-Host "Installed $InventoryId ($($lab.name)) → $ServerUrl"
  Write-Host "Check: Get-ScheduledTask -TaskName LabWatchAgent"
} finally {
  Remove-Item -Recurse -Force $work -ErrorAction SilentlyContinue
}
