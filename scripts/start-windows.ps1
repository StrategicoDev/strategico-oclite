param(
  [string]$SourceDir = "",
  [string]$OCLiteHome = "",
  [string]$HostAddress = "127.0.0.1",
  [int]$Port = 8787,
  [switch]$NoTelegram
)

$ErrorActionPreference = "Stop"

if (-not $SourceDir) {
  $SourceDir = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
} else {
  $SourceDir = (Resolve-Path $SourceDir).Path
}

if (-not $OCLiteHome) {
  $OCLiteHome = Join-Path $SourceDir ".oclite"
}

$env:OCLITE_HOME = $OCLiteHome
Set-Location $SourceDir

$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
  $python = Get-Command py -ErrorAction SilentlyContinue
}
if (-not $python) {
  throw "Python was not found on PATH."
}

$argsList = @("run.py", "run", "--host", $HostAddress, "--port", "$Port")
if ($NoTelegram) {
  $argsList += "--no-telegram"
}

Write-Host "Starting OCLite gateway..."
Write-Host "Source: $SourceDir"
Write-Host "Runtime home: $OCLiteHome"
Write-Host "URL: http://$HostAddress`:$Port"
Write-Host ""
Write-Host "Leave this window open while using OCLite. Press Ctrl+C to stop."
Write-Host ""

& $python.Source @argsList
