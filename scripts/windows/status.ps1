$ErrorActionPreference = "Continue"
$svc = Get-Service -Name "LabWatchAgent" -ErrorAction SilentlyContinue
if ($svc) {
  Get-Service -Name "LabWatchAgent" | Format-List Name, Status, StartType
} else {
  Get-ScheduledTask -TaskName "LabWatchAgent" -ErrorAction SilentlyContinue | Format-List TaskName, State
}
if (Test-Path "$env:ProgramData\LabWatch\state\state.toml") {
  Get-Content "$env:ProgramData\LabWatch\state\state.toml"
}
