#Requires -RunAsAdministrator
# LabWatch Windows installer (ASCII-only for Windows PowerShell 5.1).
# Same flow as Linux: username -> password -> machine ID -> lab -> auto token -> register.
#
# Primary (lab PCs / campus proxy) - download script from LabWatch server:
#   Invoke-WebRequest -Uri http://hobbit2.cse.iitd.ac.in:8080/install-agent.ps1 -OutFile $env:TEMP\labwatch-install.ps1
#   powershell -ExecutionPolicy Bypass -File $env:TEMP\labwatch-install.ps1
#
# Optional (no campus proxy / GitHub reachable) - always latest release asset:
#   Invoke-WebRequest -Uri https://github.com/karpus2807/iitd_lab/releases/latest/download/install-agent.ps1 -OutFile $env:TEMP\labwatch-install.ps1
#   powershell -ExecutionPolicy Bypass -File $env:TEMP\labwatch-install.ps1 -FromGitHub
#
# Default: agent pack from LabWatch server /agent-pack.tgz (same host as ServerUrl).
# -FromGitHub: agent zip from GitHub latest release tag.
param(
  [string]$ServerUrl = "",
  [switch]$FromGitHub,
  [string]$Version = "latest",
  [string]$GitHubRepo = "karpus2807/iitd_lab"
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

$InstallDir = Join-Path $env:ProgramFiles "LabWatch Agent"
$DataDir = Join-Path $env:ProgramData "LabWatch"
$ConfigPath = Join-Path $DataDir "config.toml"
$StateDir = Join-Path $DataDir "state"

function Write-Utf8NoBom([string]$Path, [string]$Content) {
  $enc = New-Object System.Text.UTF8Encoding $false
  [System.IO.File]::WriteAllText($Path, $Content, $enc)
}

function Invoke-DirectWebRequest {
  # Bypass campus proxy for LabWatch host downloads.
  param([string]$Uri, [string]$OutFile, [int]$TimeoutSec = 120)
  $oldProxy = [System.Net.WebRequest]::DefaultWebProxy
  try {
    [System.Net.WebRequest]::DefaultWebProxy = New-Object System.Net.WebProxy($null)
    Invoke-WebRequest -Uri $Uri -OutFile $OutFile -UseBasicParsing -TimeoutSec $TimeoutSec
  } finally {
    [System.Net.WebRequest]::DefaultWebProxy = $oldProxy
  }
}

function Invoke-LwJson {
  param(
    [string]$Method,
    [string]$Path,
    [hashtable]$Body = $null,
    [string]$Token = ""
  )
  $oldProxy = [System.Net.WebRequest]::DefaultWebProxy
  try {
    [System.Net.WebRequest]::DefaultWebProxy = New-Object System.Net.WebProxy($null)
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
    return Invoke-RestMethod @params
  } catch {
    $msg = $_.Exception.Message
    if ($_.ErrorDetails -and $_.ErrorDetails.Message) { $msg = $_.ErrorDetails.Message }
    throw "Request failed ($Method $Path): $msg"
  } finally {
    [System.Net.WebRequest]::DefaultWebProxy = $oldProxy
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

function ConvertTo-ObjectArray {
  param($InputObject)
  if ($null -eq $InputObject) { return @() }
  if ($InputObject -is [System.Array]) { return @($InputObject) }
  return @($InputObject)
}

function Resolve-GitHubVersion {
  if ($Version -and $Version.ToLower() -ne "latest") {
    if (-not $Version.StartsWith("v")) { return "v$Version" }
    return $Version
  }
  $api = "https://api.github.com/repos/$GitHubRepo/releases/latest"
  Write-Host "Resolving latest GitHub release..."
  $rel = Invoke-RestMethod -Uri $api -UseBasicParsing -TimeoutSec 60
  $tag = [string]$rel.tag_name
  if (-not $tag) { throw "Could not resolve latest GitHub release for $GitHubRepo" }
  return $tag
}

function Get-AgentSourceFromServer([string]$DestRoot) {
  $pack = Join-Path $DestRoot "agent-pack.tgz"
  $url = "$ServerUrl/agent-pack.tgz"
  Write-Host "Downloading agent pack from LabWatch server..."
  Write-Host "  $url"
  Invoke-DirectWebRequest -Uri $url -OutFile $pack -TimeoutSec 180
  $src = Join-Path $DestRoot "src"
  New-Item -ItemType Directory -Force -Path $src | Out-Null
  $tar = Get-Command tar.exe -ErrorAction SilentlyContinue
  if (-not $tar) { throw "tar.exe not found. Windows 10 (1803+) and Windows 11 include it." }
  & $tar.Source -xzf $pack -C $src
  if ($LASTEXITCODE -ne 0) { throw "tar failed to extract agent-pack.tgz (exit $LASTEXITCODE)" }
  if (-not (Test-Path -LiteralPath (Join-Path $src "labwatch_agent"))) {
    throw "agent-pack.tgz did not contain labwatch_agent"
  }
  return $src
}

function Get-AgentSourceFromGitHub([string]$DestRoot) {
  $tag = Resolve-GitHubVersion
  $zipUrl = "https://github.com/$GitHubRepo/archive/refs/tags/$tag.zip"
  $zipPath = Join-Path $DestRoot "repo.zip"
  Write-Host "Downloading agent $tag from GitHub..."
  Write-Host "  $zipUrl"
  Invoke-WebRequest -Uri $zipUrl -OutFile $zipPath -UseBasicParsing -TimeoutSec 300
  $extract = Join-Path $DestRoot "extract"
  New-Item -ItemType Directory -Force -Path $extract | Out-Null
  Expand-Archive -LiteralPath $zipPath -DestinationPath $extract -Force
  $repoName = ($GitHubRepo -split "/")[-1]
  $candidates = @(
    (Join-Path $extract ($repoName + "-" + $tag.TrimStart("v"))),
    (Join-Path $extract ($repoName + "-" + $tag)),
    (Get-ChildItem -LiteralPath $extract -Directory | Select-Object -First 1 -ExpandProperty FullName)
  )
  $root = $null
  foreach ($c in $candidates) {
    if ($c -and (Test-Path -LiteralPath (Join-Path $c "agent\labwatch_agent"))) {
      $root = $c
      break
    }
  }
  if (-not $root) { throw "GitHub zip did not contain agent/labwatch_agent (tag $tag)." }
  return (Join-Path $root "agent")
}

$pythonExe = Find-PythonExe
if (-not $pythonExe) {
  throw @"
Python 3.8+ is required and must be on PATH.
1) Download https://www.python.org/downloads/windows/
2) Enable 'Add python.exe to PATH'
3) Close this window, open a NEW Admin PowerShell, re-run the installer.
Do not use the Microsoft Store python stub.
"@
}
Write-Host "Using Python: $pythonExe"
Write-Host ""
Write-Host "LabWatch Windows install"
Write-Host "  Server : $ServerUrl"
if ($FromGitHub) {
  Write-Host "  Agent  : GitHub $GitHubRepo (latest unless -Version set)"
} else {
  Write-Host "  Agent  : $ServerUrl/agent-pack.tgz (LabWatch server)"
}
Write-Host "Same as Linux: login -> machine ID -> lab. Token is automatic."
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
if (-not $InventoryId) { throw "Username, password, and machine ID are required." }

Write-Host "Logging in to LabWatch (direct, no campus proxy)..."
$login = Invoke-LwJson -Method POST -Path "/api/auth/login" -Body @{ username = $Username; password = $Password }
$access = [string]$login.access_token
if (-not $access) { throw "Login failed. Use a LabWatch ADMIN or OPERATOR account (not SSH)." }

Write-Host "Loading lab list..."
$labs = ConvertTo-ObjectArray (Invoke-LwJson -Method GET -Path "/api/labs" -Token $access)
if ($labs.Count -eq 0) { throw "No labs found. Create labs in Admin first." }
$labs = ConvertTo-ObjectArray (
  $labs | Sort-Object -Property @(
    @{ Expression = { if (("" + $_.name).Trim().ToLower() -eq "unassigned") { 0 } else { 1 } } },
    @{ Expression = "name" }
  )
)

$currentLab = $null
$listed = ConvertTo-ObjectArray (Invoke-LwJson -Method GET -Path ("/api/machines?inventory_id=" + [uri]::EscapeDataString($InventoryId)) -Token $access)
if ($listed.Count -gt 0 -and $listed[0].lab_id) {
  $want = [string]$listed[0].lab_id
  foreach ($row in $labs) {
    if ([string]$row.id -eq $want) { $currentLab = $row; break }
  }
}
if (-not $currentLab -and $ExistingLabId) {
  foreach ($row in $labs) {
    if ([string]$row.id -eq $ExistingLabId) { $currentLab = $row; break }
  }
}
if (-not $currentLab -and $ExistingLabName) {
  foreach ($row in $labs) {
    if (("" + $row.name).Trim().ToLower() -eq $ExistingLabName.ToLower()) { $currentLab = $row; break }
  }
}
if (-not $currentLab) {
  foreach ($row in $labs) {
    if (("" + $row.name).Trim().ToLower() -eq "unassigned") { $currentLab = $row; break }
  }
}
if (-not $currentLab) { $currentLab = $labs[0] }

Write-Host ""
Write-Host "Labs:"
for ($i = 0; $i -lt $labs.Count; $i++) {
  $row = $labs[$i]
  $rowName = [string]$row.name
  $rowId = [string]$row.id
  $mark = if ($rowId -eq [string]$currentLab.id) { "  [current]" } else { "" }
  $count = $row.machine_count
  if ($count -is [System.Array]) { $count = $count[0] }
  $hosts = if ($null -ne $count -and "$count" -ne "") { "  ($count hosts)" } else { "" }
  Write-Host ("  {0}) {1}{2}{3}" -f ($i + 1), $rowName, $hosts, $mark)
}
$choice = Read-Host ("Select lab number (Enter keeps {0})" -f ([string]$currentLab.name))
$lab = $currentLab
if ($choice) {
  $n = 0
  if (-not [int]::TryParse($choice, [ref]$n) -or $n -lt 1 -or $n -gt $labs.Count) {
    throw "Lab number must be between 1 and $($labs.Count)"
  }
  $lab = $labs[$n - 1]
  Write-Host ("Selected {0}" -f ([string]$lab.name))
} else {
  Write-Host ("Keeping {0}" -f ([string]$lab.name))
}

Write-Host "Enrolling $InventoryId..."
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
Write-Host "Enrollment OK (token kept in config - you do not copy it)."

New-Item -ItemType Directory -Force -Path $InstallDir, $DataDir, $StateDir | Out-Null
$work = Join-Path $env:TEMP ("labwatch-agent-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Force -Path $work | Out-Null
try {
  if ($FromGitHub) {
    $agentSrc = Get-AgentSourceFromGitHub -DestRoot $work
  } else {
    $agentSrc = Get-AgentSourceFromServer -DestRoot $work
  }
  if (-not (Test-Path -LiteralPath (Join-Path $agentSrc "requirements.txt"))) {
    throw "agent/requirements.txt missing in agent download"
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
  & $py -m pip install -r (Join-Path $agentSrc "requirements.txt")
  if ($LASTEXITCODE -ne 0) { throw "pip install requirements failed (check network / campus proxy for pypi.org)" }

  $destPkg = Join-Path $InstallDir "labwatch_agent"
  if (Test-Path -LiteralPath $destPkg) { Remove-Item -LiteralPath $destPkg -Recurse -Force }
  Copy-Item -Recurse -Force (Join-Path $agentSrc "labwatch_agent") $InstallDir

  $runPy = Join-Path $InstallDir "run.py"
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

  Write-Host "Registering machine with LabWatch server..."
  $env:LABWATCH_CONFIG = $ConfigPath
  $env:LABWATCH_STATE_DIR = $StateDir
  & $py $runPy register
  if ($LASTEXITCODE -ne 0) {
    throw "Machine registration failed. Check that $ServerUrl is reachable from this PC."
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
  Write-Host "Open LabWatch -> Machines to confirm this PC."
} finally {
  Remove-Item -Recurse -Force $work -ErrorAction SilentlyContinue
}
