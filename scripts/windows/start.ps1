Start-ScheduledTask -TaskName "LabWatchAgent"
Get-ScheduledTask -TaskName "LabWatchAgent" | Format-List TaskName, State
