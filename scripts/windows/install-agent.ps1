#Requires -RunAsAdministrator
# LabWatch Windows installer - same flow as Linux install-agent.sh:
#   username + password -> machine ID -> lab -> server mints one-use token -> register machine
# Recommended (Admin PowerShell):
#   Invoke-WebRequest -Uri http://hobbit2.cse.iitd.ac.in:8080/install-agent.ps1 -OutFile $env:TEMP\labwatch-install.ps1
#   powershell -ExecutionPolicy Bypass -File $env:TEMP\labwatch-install.ps1
# ASCII-only file: Windows PowerShell 5.1 mis-parses UTF-8 em-dashes without a BOM.
param(
  [string]$ServerUrl = ""
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

try {
  [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
} catch { }

if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)) {
  throw "Run this in an elevated Admin PowerShell (right-click PowerShell -> Run as administrator)."
}

if (-not $ServerUrl) { $ServerUrl = "__SERVER_URL__" }
if ($ServerUrl -eq "__SERVER_URL__" -or -not $ServerUrl) {
  $ServerUrl = "http://hobbit2.cse.iitd.ac.in:8080"
}
$ServerUrl = $ServerUrl.TrimEnd("/")
$ServerHost = ([Uri]$ServerUrl).Host

$env:NO_PROXY = (($env:NO_PROXY, $ServerHost, "localhost", "127.0.0.1") -join ",").Trim(",")
$env:no_proxy = $env:NO_PROXY
try {
  [System.Net.WebRequest]::DefaultWebProxy = New-Object System.Net.WebProxy($null)
} catch { }

$InstallDir = Join-Path $env:ProgramFiles "LabWatch Agent"
$DataDir = Join-Path $env:ProgramData "LabWatch"
$ConfigPath = Join-Path $DataDir "config.toml"
$StateDir = Join-Path $DataDir "state"

function Write-Utf8NoBom([string]$Path, [string]$Content) {
  $enc = New-Object System.Text.UTF8Encoding $false
  [System.IO.File]::WriteAllText($Path, $Content, $enc)
}

function Invoke-LwJson {
  param(
    [string]$Method,
    [string]$Path,
    [hashtable]$Body = $null,
    [string]$Token = ""
  )
  $headers = @{ "Content-Type" = "application/json"; "Accept" = "application/json" }
  if ($Token) { $headers["Authorization"] = "Bearer $Token" }
  $params = @{
    Method          = $Method
    Uri             = "$ServerUrl$Path"
    Headers         = $headers
    UseBasicParsing = $true
    TimeoutSec      = 60
  }
  if ($Body) { $params.Body = ($Body | ConvertTo-Json -Compress -Depth 8) }
  try {
    return Invoke-RestMethod @params
  } catch {
    $msg = $_.Exception.Message
    if ($_.ErrorDetails -and $_.ErrorDetails.Message) { $msg = $_.ErrorDetails.Message }
    throw "Request failed ($Method $Path): $msg"
  }
}

function Find-PythonExe {
  $trials = @(
    @{ File = "py"; Args = @("-3") },
    @{ File = "python"; Args = @() },
    @{ File = "python3"; Args = @() }
  )
  foreach ($t in $trials) {
    $cmd = Get-Command $t.File -ErrorAction SilentlyContinue
    if (-not $cmd) { continue }
    try {
      $exe = & $cmd.Source @($t.Args + @("-c", "import sys; assert sys.version_info >= (3, 8); print(sys.executable)")) 2>$null
      if (-not $exe) { continue }
      $exe = ([string]$exe).Trim()
      if ($exe -match '\\WindowsApps\\') { continue }
      if (Test-Path -LiteralPath $exe) { return $exe }
    } catch { }
  }
  return $null
}

function Expand-AgentPack([string]$Archive, [string]$Dest) {
  New-Item -ItemType Directory -Force -Path $Dest | Out-Null
  $tar = Get-Command tar.exe -ErrorAction SilentlyContinue
  if (-not $tar) {
    throw "tar.exe not found. Windows 10 (1803+) and Windows 11 include it."
  }
  & $tar.Source -xzf $Archive -C $Dest
  if ($LASTEXITCODE -ne 0) { throw "tar failed to extract agent-pack.tgz (exit $LASTEXITCODE)" }
}

# --- same prerequisites order as Linux ---
$pythonExe = Find-PythonExe
if (-not $pythonExe) {
  throw @"
Python 3.8+ is required and must be on PATH (same idea as Linux python3).
1) Download https://www.python.org/downloads/windows/
2) Enable 'Add python.exe to PATH'
3) Close this window, open a NEW Admin PowerShell, re-run the installer.
Do not use the Microsoft Store python stub.
"@
}
Write-Host "Using Python: $pythonExe"

Write-Host ""
Write-Host "LabWatch agent install -> $ServerUrl"
Write-Host "Same process as Linux: login -> machine ID -> lab. Token is created for you (do not paste an Admin token)."
Write-Host "Multiple PCs can use the same admin/operator login."

$Username = Read-Host "Username"
$Secure = Read-Host "Password (nothing will appear)" -AsSecureString
$BSTR = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($Secure)
try {
  $Password = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($BSTR)
} finally {
  [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($BSTR) | Out-Null
}
if (-not $Username -or -not $Password) { throw "Username and password are required." }
Write-Host "Password received. Asking for machine ID next..."

$ExistingId = ""
$ExistingLabId = ""
$ExistingLabName = ""
if (Test-Path -LiteralPath $ConfigPath) {
  Write-Host "Existing LabWatch agent found. Enter keeps the current machine ID and lab."
  $m = Select-String -Path $ConfigPath -Pattern '^\s*inventory_id\s*=\s*"([^"]+)"' | Select-Object -First 1
  if ($m) { $ExistingId = $m.Matches[0].Groups[1].Value.Trim() }
  $m = Select-String -Path $ConfigPath -Pattern '^\s*lab_id\s*=\s*"([^"]+)"' | Select-Object -First 1
  if ($m) { $ExistingLabId = $m.Matches[0].Groups[1].Value.Trim() }
  $m = Select-String -Path $ConfigPath -Pattern '^\s*lab\s*=\s*"([^"]+)"' | Select-Object -First 1
  if ($m) { $ExistingLabName = $m.Matches[0].Groups[1].Value.Trim() }
}
$hint = if ($ExistingId) { $ExistingId } else { "example 12345/2012/12" }
$InventoryId = Read-Host "Machine ID [$hint]"
if (-not $InventoryId) { $InventoryId = $ExistingId }
if (-not $InventoryId) { throw "Username, password, and machine ID are required (Enter keeps the previous machine ID if one exists)." }

Write-Host "Logging in..."
$login = Invoke-LwJson -Method POST -Path "/api/auth/login" -Body @{ username = $Username; password = $Password }
$access = [string]$login.access_token
if (-not $access) { throw "Login failed. Use a LabWatch ADMIN or OPERATOR account (not SSH)." }

Write-Host "Loading lab list..."
$labs = @(Invoke-LwJson -Method GET -Path "/api/labs" -Token $access)
if ($labs.Count -eq 0) { throw "No labs found. Create labs in Admin first." }
$labs = @($labs | Sort-Object { if (("" + $_.name).Trim().ToLower() -eq "unassigned") { 0 } else { 1 } }, name)

$currentLab = $null
$listed = @(Invoke-LwJson -Method GET -Path ("/api/machines?inventory_id=" + [uri]::EscapeDataString($InventoryId)) -Token $access)
if ($listed.Count -gt 0 -and $listed[0].lab_id) {
  $currentLab = $labs | Where-Object { [string]$_.id -eq [string]$listed[0].lab_id } | Select-Object -First 1
}
if (-not $currentLab -and $ExistingLabId) {
  $currentLab = $labs | Where-Object { [string]$_.id -eq $ExistingLabId } | Select-Object -First 1
}
if (-not $currentLab -and $ExistingLabName) {
  $currentLab = $labs | Where-Object { ("" + $_.name).Trim().ToLower() -eq $ExistingLabName.ToLower() } | Select-Object -First 1
}
if (-not $currentLab) {
  $currentLab = $labs | Where-Object { ("" + $_.name).Trim().ToLower() -eq "unassigned" } | Select-Object -First 1
}
if (-not $currentLab) { $currentLab = $labs[0] }

Write-Host ""
Write-Host "Labs:"
for ($i = 0; $i -lt $labs.Count; $i++) {
  $mark = if ([string]$labs[$i].id -eq [string]$currentLab.id) { "  [current]" } else { "" }
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
  Write-Host "Selected $($lab.name)"
} else {
  Write-Host "Keeping $($lab.name)"
}

Write-Host "Logging in to $ServerUrl and enrolling $InventoryId..."
$enroll = Invoke-LwJson -Method POST -Path "/api/agents/enroll" -Body @{
  username     = $Username
  password     = $Password
  inventory_id = $InventoryId
  lab_id       = [string]$lab.id
}
$Password = $null
$Username = $null
$Token = [string]$enroll.registration_token
if ($enroll.server_url) { $ServerUrl = ([string]$enroll.server_url).TrimEnd("/") }
if (-not $Token) { throw "Enroll did not return a registration token." }
Write-Host "Enrollment token created (one-use, kept in config - you do not need to copy it)."

New-Item -ItemType Directory -Force -Path $InstallDir, $DataDir, $StateDir | Out-Null
$work = Join-Path $env:TEMP ("labwatch-agent-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Force -Path $work | Out-Null
try {
  $pack = Join-Path $work "agent-pack.tgz"
  Write-Host "Downloading agent from $ServerUrl/agent-pack.tgz"
  Invoke-WebRequest -Uri "$ServerUrl/agent-pack.tgz" -OutFile $pack -UseBasicParsing -TimeoutSec 120
  $src = Join-Path $work "src"
  Expand-AgentPack -Archive $pack -Dest $src
  if (-not (Test-Path -LiteralPath (Join-Path $src "labwatch_agent"))) {
    throw "agent-pack.tgz did not contain labwatch_agent"
  }

  Write-Host "Installing LabWatch agent to $InstallDir"
  Get-ScheduledTask -TaskName "LabWatchAgent" -ErrorAction SilentlyContinue |
    Unregister-ScheduledTask -Confirm:$false -ErrorAction SilentlyContinue

  $venvDir = Join-Path $InstallDir "venv"
  if (Test-Path -LiteralPath $venvDir) { Remove-Item -LiteralPath $venvDir -Recurse -Force }
  & $pythonExe -m venv $venvDir
  $py = Join-Path $venvDir "Scripts\python.exe"
  if (-not (Test-Path -LiteralPath $py)) { throw "venv python missing at $py" }

  & $py -m pip install -U pip
  if ($LASTEXITCODE -ne 0) { throw "pip upgrade failed" }
  & $py -m pip install -r (Join-Path $src "requirements.txt")
  if ($LASTEXITCODE -ne 0) { throw "pip install requirements failed (check campus proxy / network)" }

  $destPkg = Join-Path $InstallDir "labwatch_agent"
  if (Test-Path -LiteralPath $destPkg) { Remove-Item -LiteralPath $destPkg -Recurse -Force }
  Copy-Item -Recurse -Force (Join-Path $src "labwatch_agent") $InstallDir

  $runPy = Join-Path $InstallDir "run.py"
  # Single-quoted here-string so PowerShell never parses the Python source.
  Write-Utf8NoBom $runPy @'
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from labwatch_agent.service import main
if __name__ == "__main__":
    raise SystemExit(main())
'@

  $site = & $py -c "import sysconfig; print(sysconfig.get_path('purelib'))"
  Write-Utf8NoBom (Join-Path $site.Trim() "labwatch.pth") $InstallDir

  $labToml = ([string]$lab.name).Replace('\', '\\').Replace('"', '\"')
  $configText = @"
[server]
url = "$ServerUrl"
registration_token = "$Token"
inventory_id = "$InventoryId"
lab_id = "$([string]$lab.id)"
lab = "$labToml"

[agent]
heartbeat_interval = 30
metric_interval = 30
inventory_interval = 300

[tls]
verify = true

[logging]
level = "INFO"
"@
  Write-Utf8NoBom $ConfigPath $configText
  icacls $ConfigPath /inheritance:r /grant:r "SYSTEM:F" "Administrators:F" | Out-Null
  Remove-Item -Force (Join-Path $StateDir "state.toml") -ErrorAction SilentlyContinue

  Write-Host "Registering machine with server (same as Linux agent first start)..."
  $env:LABWATCH_CONFIG = $ConfigPath
  $env:LABWATCH_STATE_DIR = $StateDir
  & $py $runPy register
  if ($LASTEXITCODE -ne 0) {
    throw "Machine registration failed. Check server URL $ServerUrl and try again."
  }

  $action = New-ScheduledTaskAction -Execute $py -Argument "`"$runPy`" run" -WorkingDirectory $InstallDir
  $trigger = New-ScheduledTaskTrigger -AtStartup
  $principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
  $settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -RestartCount 5 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -StartWhenAvailable
  Register-ScheduledTask -TaskName "LabWatchAgent" -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null
  Start-ScheduledTask -TaskName "LabWatchAgent"
  Start-Sleep -Seconds 2
  $task = Get-ScheduledTask -TaskName "LabWatchAgent"

  Write-Host "Installed $InventoryId ($($lab.name)) -> $ServerUrl"
  Write-Host ("Scheduled task: {0}" -f $task.State)
  Write-Host "Update later with the same PowerShell command; Enter keeps this machine ID and lab."
  Write-Host "Commands: `"$py`" `"$runPy`" status"
} finally {
  Remove-Item -Recurse -Force $work -ErrorAction SilentlyContinue
}
