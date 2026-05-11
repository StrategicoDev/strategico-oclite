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

function Resolve-Python {
  $candidates = @()
  if ($env:OCLITE_PYTHON) {
    $candidates += @{ Exe = $env:OCLITE_PYTHON; Args = @(); Label = "OCLITE_PYTHON" }
  }
  $candidates += @{ Exe = (Join-Path $SourceDir ".venv\Scripts\python.exe"); Args = @(); Label = "repo virtualenv" }
  $candidates += @{ Exe = (Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"); Args = @(); Label = "Codex bundled Python" }
  $candidates += @{ Exe = "py"; Args = @("-3"); Label = "Python launcher" }
  $candidates += @{ Exe = "python3"; Args = @(); Label = "python3 on PATH" }
  $candidates += @{ Exe = "python"; Args = @(); Label = "python on PATH" }

  foreach ($candidate in $candidates) {
    $exe = $candidate.Exe
    $isPath = $exe -match "[\\/]" -or $exe -match "^[A-Za-z]:"
    if ($isPath) {
      if (-not (Test-Path $exe)) {
        continue
      }
    } elseif (-not (Get-Command $exe -ErrorAction SilentlyContinue)) {
      continue
    }

    try {
      $versionArgs = @($candidate.Args) + @("--version")
      $version = & $exe @versionArgs 2>&1
      if ($LASTEXITCODE -eq 0 -and "$version" -match "Python\s+\d") {
        return [pscustomobject]@{
          Exe = $exe
          Args = @($candidate.Args)
          Label = $candidate.Label
          Version = "$version"
        }
      }
    } catch {
      continue
    }
  }

  throw "A real Python executable was not found. Install Python, use the Python Launcher, or set OCLITE_PYTHON to a python.exe path."
}

$python = Resolve-Python
$argsList = @("run.py", "run", "--host", $HostAddress, "--port", "$Port")
if ($NoTelegram) {
  $argsList += "--no-telegram"
}

Write-Host "Starting OCLite gateway..."
Write-Host "Source: $SourceDir"
Write-Host "Runtime home: $OCLiteHome"
Write-Host "Python: $($python.Label) - $($python.Version)"
Write-Host "URL: http://$HostAddress`:$Port"
Write-Host ""
Write-Host "Leave this window open while using OCLite. Press Ctrl+C to stop."
Write-Host ""

$invokeArgs = @($python.Args) + $argsList
& $python.Exe @invokeArgs
