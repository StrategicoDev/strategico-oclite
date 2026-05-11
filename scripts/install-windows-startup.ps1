param(
  [string]$SourceDir = "",
  [string]$OCLiteHome = "$env:USERPROFILE\.oclite",
  [string]$HostAddress = "127.0.0.1",
  [int]$Port = 8787,
  [string]$TaskName = "OCLite Gateway",
  [switch]$Remove
)

$ErrorActionPreference = "Stop"

if ($Remove) {
  Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
  Write-Host "Removed scheduled task '$TaskName'."
  exit 0
}

if (-not $SourceDir) {
  $SourceDir = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
} else {
  $SourceDir = (Resolve-Path $SourceDir).Path
}

$runDir = Join-Path $env:APPDATA "OCLite"
$starter = Join-Path $runDir "start-oclite.ps1"
$log = Join-Path $runDir "gateway.log"
New-Item -ItemType Directory -Force -Path $runDir | Out-Null

$starterContent = @"
`$ErrorActionPreference = "Stop"
`$env:OCLITE_HOME = "$OCLiteHome"
& "$SourceDir\scripts\start-windows.ps1" -SourceDir "$SourceDir" -OCLiteHome "$OCLiteHome" -HostAddress "$HostAddress" -Port $Port *> "$log"
"@

Set-Content -Path $starter -Value $starterContent -Encoding UTF8

$action = New-ScheduledTaskAction `
  -Execute "powershell.exe" `
  -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$starter`""
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet `
  -AllowStartIfOnBatteries `
  -DisallowStartIfOnBatteries:$false `
  -ExecutionTimeLimit (New-TimeSpan -Days 30) `
  -RestartCount 3 `
  -RestartInterval (New-TimeSpan -Minutes 1)

Register-ScheduledTask `
  -TaskName $TaskName `
  -Action $action `
  -Trigger $trigger `
  -Settings $settings `
  -Description "Starts the OCLite gateway at user login." `
  -Force | Out-Null

Write-Host "Installed scheduled task '$TaskName'."
Write-Host "Source: $SourceDir"
Write-Host "Runtime home: $OCLiteHome"
Write-Host "URL: http://$HostAddress`:$Port"
Write-Host "Starter: $starter"
Write-Host "Log: $log"
Write-Host ""
Write-Host "Start it now with:"
Write-Host "  Start-ScheduledTask -TaskName `"$TaskName`""
Write-Host ""
Write-Host "Remove it with:"
Write-Host "  powershell -ExecutionPolicy Bypass -File `"$PSCommandPath`" -Remove"
