#Requires -RunAsAdministrator
$ErrorActionPreference = "Continue"
$svc = Get-Service -Name "LabWatchAgent" -ErrorAction SilentlyContinue
if ($svc) {
  Stop-Service -Name "LabWatchAgent" -Force -ErrorAction SilentlyContinue
  Write-Host "stopped service LabWatchAgent"
} else {
  Stop-ScheduledTask -TaskName "LabWatchAgent" -ErrorAction SilentlyContinue
  Write-Host "stopped scheduled task LabWatchAgent"
}
