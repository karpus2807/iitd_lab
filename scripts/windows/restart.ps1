#Requires -RunAsAdministrator
$ErrorActionPreference = "Continue"
$svc = Get-Service -Name "LabWatchAgent" -ErrorAction SilentlyContinue
if ($svc) {
  Restart-Service -Name "LabWatchAgent" -Force
  Get-Service -Name "LabWatchAgent" | Format-List Name, Status, StartType
  Write-Host "restarted service"
} else {
  Stop-ScheduledTask -TaskName "LabWatchAgent" -ErrorAction SilentlyContinue
  Start-Sleep -Seconds 2
  Start-ScheduledTask -TaskName "LabWatchAgent" -ErrorAction SilentlyContinue
  Write-Host "restarted scheduled task"
}
