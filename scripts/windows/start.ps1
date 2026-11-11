#Requires -RunAsAdministrator
$ErrorActionPreference = "Continue"
$svc = Get-Service -Name "LabWatchAgent" -ErrorAction SilentlyContinue
if ($svc) {
  Start-Service -Name "LabWatchAgent"
  Get-Service -Name "LabWatchAgent" | Format-List Name, Status, StartType
} else {
  Start-ScheduledTask -TaskName "LabWatchAgent" -ErrorAction SilentlyContinue
  Get-ScheduledTask -TaskName "LabWatchAgent" -ErrorAction SilentlyContinue | Format-List TaskName, State
}
