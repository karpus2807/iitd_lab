#Requires -RunAsAdministrator
Stop-ScheduledTask -TaskName "LabWatchAgent" -ErrorAction SilentlyContinue
Unregister-ScheduledTask -TaskName "LabWatchAgent" -Confirm:$false -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force "$env:ProgramFiles\LabWatch Agent" -ErrorAction SilentlyContinue
Write-Host "Uninstalled. Config/state under $env:ProgramData\LabWatch was kept."
