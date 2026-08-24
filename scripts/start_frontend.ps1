[CmdletBinding()]
param(
    [int]$Port = 5173,
    [string]$HostName = "localhost"
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$frontendRoot = Join-Path $repoRoot "frontend"

if (-not (Test-Path (Join-Path $frontendRoot "package.json"))) {
    throw "Frontend package.json not found under $frontendRoot"
}

$listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
if ($listener) {
    $process = Get-CimInstance Win32_Process -Filter "ProcessId=$($listener.OwningProcess)" -ErrorAction SilentlyContinue
    $commandLine = if ($process) { $process.CommandLine } else { "<unknown>" }
    throw "Port $Port is already in use by PID $($listener.OwningProcess): $commandLine`nStop that process first or choose another port with -Port."
}

Set-Location $frontendRoot
Write-Host "Starting React/Vite frontend on http://${HostName}:$Port ..." -ForegroundColor Cyan
Write-Host "Vite strictPort is enabled so it will not silently move to another port." -ForegroundColor DarkGray
npm run dev -- --host $HostName --port $Port --strictPort
