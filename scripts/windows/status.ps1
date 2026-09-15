Get-ScheduledTask -TaskName "LabWatchAgent" -ErrorAction SilentlyContinue | Format-List TaskName, State
if (Test-Path "$env:ProgramData\LabWatch\state\state.toml") {
  Get-Content "$env:ProgramData\LabWatch\state\state.toml"
}
