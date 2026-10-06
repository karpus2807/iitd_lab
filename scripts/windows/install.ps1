#Requires -RunAsAdministrator
# Deprecated token-based installer. Prefer the Linux-same enroll flow:
#   irm http://hobbit2.cse.iitd.ac.in:8080/install-agent.ps1 | iex
param(
  [Parameter(Mandatory = $false)][string]$ServerUrl = "",
  [Parameter(Mandatory = $false)][string]$RegistrationToken = ""
)

$ErrorActionPreference = "Stop"
Write-Host "This script is deprecated."
Write-Host "Windows now uses the same login flow as Linux (username/password → machine ID → lab; token is automatic)."
Write-Host ""
Write-Host "Run instead (Admin PowerShell):"
if (-not $ServerUrl) { $ServerUrl = "http://hobbit2.cse.iitd.ac.in:8080" }
Write-Host "  Invoke-WebRequest -Uri $ServerUrl/install-agent.ps1 -OutFile `$env:TEMP\labwatch-install.ps1"
Write-Host "  powershell -ExecutionPolicy Bypass -File `$env:TEMP\labwatch-install.ps1"
if ($RegistrationToken) {
  Write-Host ""
  Write-Host "A RegistrationToken was passed but is no longer needed — the installer logs in and enrolls for you."
}
exit 1
