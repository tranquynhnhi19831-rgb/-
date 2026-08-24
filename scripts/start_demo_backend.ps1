[CmdletBinding()]
param(
    [int]$Port = 8010,
    [string]$ProxyUrl = ""
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"

function Read-HiddenText([string]$Prompt) {
    $secure = Read-Host $Prompt -AsSecureString
    $ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try {
        return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr)
    }
    finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr)
    }
}

function Normalize-ProxyUrl([string]$RawValue) {
    if ($null -eq $RawValue) {
        $value = ""
    }
    else {
        $value = $RawValue.Trim()
    }
    if (-not $value) { return "" }

    # Windows may store protocol-specific proxies as
    # "http=127.0.0.1:7890;https=127.0.0.1:7890".
    if ($value.Contains("=")) {
        $entries = @{}
        foreach ($part in ($value -split ";")) {
            if ($part -match "^\s*([^=]+)=(.+)$") {
                $entries[$matches[1].Trim().ToLowerInvariant()] = $matches[2].Trim()
            }
        }
        if ($entries.ContainsKey("https")) {
            $value = $entries["https"]
        }
        elseif ($entries.ContainsKey("http")) {
            $value = $entries["http"]
        }
    }

    if ($value -notmatch "^[a-zA-Z][a-zA-Z0-9+.-]*://") {
        $value = "http://$value"
    }
    return $value
}

if (-not (Test-Path $python)) {
    throw "Python virtual environment not found: $python. Run scripts/setup.ps1 first."
}

Set-Location $repoRoot
$env:PYTHONPATH = Join-Path $repoRoot "backend"

if (-not $ProxyUrl) {
    $ProxyUrl = $env:HTTPS_PROXY
}
if (-not $ProxyUrl) {
    $ProxyUrl = $env:HTTP_PROXY
}
if (-not $ProxyUrl) {
    try {
        $internet = Get-ItemProperty "HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings" -ErrorAction Stop
        if ($internet.ProxyEnable -eq 1 -and $internet.ProxyServer) {
            $ProxyUrl = [string]$internet.ProxyServer
        }
    }
    catch {
        # No Windows user proxy configured; direct access remains possible.
    }
}
$ProxyUrl = Normalize-ProxyUrl $ProxyUrl

if ($ProxyUrl) {
    $env:HTTP_PROXY = $ProxyUrl
    $env:HTTPS_PROXY = $ProxyUrl
    $env:NO_PROXY = "127.0.0.1,localhost"
    Write-Host "Binance Demo proxy configured: $ProxyUrl" -ForegroundColor Cyan
}
else {
    Write-Host "No proxy configured; Binance Demo will use direct network access." -ForegroundColor Yellow
}

if (-not $env:BINANCE_TESTNET_API_KEY) {
    $env:BINANCE_TESTNET_API_KEY = Read-HiddenText "Binance Demo API Key"
}
if (-not $env:BINANCE_TESTNET_SECRET) {
    $env:BINANCE_TESTNET_SECRET = Read-HiddenText "Binance Demo Secret"
}

if (-not $env:BINANCE_TESTNET_API_KEY -or -not $env:BINANCE_TESTNET_SECRET) {
    throw "Binance Demo API Key/Secret must both be configured."
}

# This launcher is for authenticated validation only. Actual virtual order routes
# stay fail-closed until they are enabled deliberately in a later acceptance step.
$env:ENABLE_BINANCE_TESTNET_ORDERS = "false"

$listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
if ($listener) {
    $process = Get-CimInstance Win32_Process -Filter "ProcessId=$($listener.OwningProcess)" -ErrorAction SilentlyContinue
    $commandLine = if ($process) { $process.CommandLine } else { "<unknown>" }
    throw "Port $Port is already in use by PID $($listener.OwningProcess): $commandLine`nStop that process first or choose another port with -Port."
}

Write-Host "Credentials configured: True" -ForegroundColor Green
Write-Host "Actual Demo order routes enabled: False" -ForegroundColor Green
Write-Host "Running public Binance Demo preflight through the project gateway..." -ForegroundColor Cyan

& $python -c "from exchange.testnet_gateway import BinanceTestnetGateway, TestnetCredentials; g=BinanceTestnetGateway(TestnetCredentials.from_env()); x=g.exchange.fapiPublicGetTime(); print('BINANCE_DEMO_PUBLIC_OK', bool(x.get('serverTime')))"
if ($LASTEXITCODE -ne 0) {
    throw "Binance Demo public preflight failed. Check the configured network/proxy before retrying."
}

Write-Host "Starting authenticated Binance Demo validation backend on http://127.0.0.1:$Port ..." -ForegroundColor Cyan
Write-Host "Use GET /api/testnet/status, then GET /api/testnet/health. Do not share API credentials in screenshots." -ForegroundColor DarkGray
& $python -m uvicorn main:app --app-dir backend --host 127.0.0.1 --port $Port
