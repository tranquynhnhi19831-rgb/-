[CmdletBinding()]
param(
    [int]$Port = 8000,
    [switch]$Reload
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $python)) {
    throw "Python virtual environment not found: $python. Run scripts/setup.ps1 first."
}

$listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
if ($listener) {
    $process = Get-CimInstance Win32_Process -Filter "ProcessId=$($listener.OwningProcess)" -ErrorAction SilentlyContinue
    $commandLine = if ($process) { $process.CommandLine } else { "<unknown>" }
    throw "Port $Port is already in use by PID $($listener.OwningProcess): $commandLine`nStop that process first or choose another port with -Port."
}

Set-Location $repoRoot
$env:PYTHONPATH = Join-Path $repoRoot "backend"

$uvicornArgs = @(
    "-m", "uvicorn", "main:app",
    "--app-dir", "backend",
    "--host", "127.0.0.1",
    "--port", "$Port"
)
if ($Reload) {
    $uvicornArgs += "--reload"
}

$mode = if ($Reload) { "development reload" } else { "stable single-process" }
Write-Host "Starting private/admin FastAPI on http://127.0.0.1:$Port ($mode) ..." -ForegroundColor Cyan
Write-Host "Project root: $repoRoot" -ForegroundColor DarkGray
& $python @uvicornArgs
