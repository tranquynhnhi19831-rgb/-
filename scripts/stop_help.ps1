$repoRoot = Split-Path -Parent $PSScriptRoot
$stopScript = Join-Path $PSScriptRoot "stop_local_stack.ps1"

Write-Host "Safe ways to stop the Jianghe local system:" -ForegroundColor Yellow
Write-Host "1) Preferred: press Ctrl+C in each runtime terminal." -ForegroundColor Yellow
Write-Host "2) Or stop only Jianghe listener processes with:" -ForegroundColor Yellow
Write-Host "   powershell -ExecutionPolicy Bypass -File `"$stopScript`"" -ForegroundColor Cyan
Write-Host "" 
Write-Host "Do NOT use 'Get-Process node,python | Stop-Process' because it can terminate unrelated Python/Node programs." -ForegroundColor Red
Write-Host "Project root: $repoRoot" -ForegroundColor DarkGray
