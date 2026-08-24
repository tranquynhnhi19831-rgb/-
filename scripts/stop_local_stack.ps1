[CmdletBinding()]
param(
    [int[]]$Ports = @(8000, 8001, 8010, 5173)
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$repoName = Split-Path $repoRoot -Leaf

function Find-ProjectProcessRoot([int]$ProcessId) {
    $current = $ProcessId
    $candidate = $ProcessId

    for ($i = 0; $i -lt 8 -and $current -gt 0; $i++) {
        $process = Get-CimInstance Win32_Process -Filter "ProcessId=$current" -ErrorAction SilentlyContinue
        if (-not $process) { break }

        $command = [string]$process.CommandLine
        if ($command -and $command.Contains($repoName) -and ($command -match "uvicorn|vite")) {
            $candidate = [int]$process.ProcessId
        }

        if (-not $process.ParentProcessId -or $process.ParentProcessId -eq $current) { break }
        $current = [int]$process.ParentProcessId
    }

    return $candidate
}

$stopped = @{}
foreach ($port in $Ports) {
    $listeners = @(Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue)
    foreach ($listener in $listeners) {
        $rootPid = Find-ProjectProcessRoot ([int]$listener.OwningProcess)
        if ($stopped.ContainsKey($rootPid)) { continue }

        $process = Get-CimInstance Win32_Process -Filter "ProcessId=$rootPid" -ErrorAction SilentlyContinue
        $command = if ($process) { [string]$process.CommandLine } else { "<unknown>" }

        if ($command -notmatch "uvicorn|vite" -and $command -notmatch [regex]::Escape($repoName)) {
            Write-Host "Skipping port $port PID $rootPid because it does not look like a $repoName runtime: $command" -ForegroundColor Yellow
            continue
        }

        Write-Host "Stopping $repoName runtime on port $port (PID $rootPid) ..." -ForegroundColor Cyan
        & taskkill.exe /PID $rootPid /T /F | Out-Host
        $stopped[$rootPid] = $true
    }
}

Start-Sleep -Milliseconds 500
$remaining = @()
foreach ($port in $Ports) {
    $remaining += @(Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue)
}

if ($remaining.Count -eq 0) {
    Write-Host "Local Jianghe runtime ports are clear." -ForegroundColor Green
}
else {
    Write-Host "Some requested ports are still listening. Inspect them before restarting:" -ForegroundColor Yellow
    $remaining | Select-Object LocalAddress, LocalPort, OwningProcess | Format-Table | Out-Host
}
