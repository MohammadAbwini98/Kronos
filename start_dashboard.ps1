$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
$symbol = if ($env:SIGNAL_SYMBOL) { $env:SIGNAL_SYMBOL } else { "ETHUSD" }
$market = if ($env:CAPITAL_DEFAULT_MARKET_SEARCH) { $env:CAPITAL_DEFAULT_MARKET_SEARCH } else { "ETHUSD" }
$resolution = if ($env:SIGNAL_RESOLUTION) { $env:SIGNAL_RESOLUTION } else { "MINUTE_5" }
$intervalMinutes = if ($env:SIGNAL_INTERVAL_MINUTES) { $env:SIGNAL_INTERVAL_MINUTES } else { "5" }
$envName = if ($env:CAPITAL_ENV) { $env:CAPITAL_ENV } else { "demo" }

$schedulerArgs = @(
    "src\main_prediction_scheduler.py",
    "--symbol", $symbol,
    "--market", $market,
    "--resolution", $resolution,
    "--interval-minutes", $intervalMinutes,
    "--env", $envName
)

if ($env:POSTGRES_DSN) {
    $schedulerArgs += @("--postgres-dsn", $env:POSTGRES_DSN)
}

$validationArgs = @(
    "src\main_validation_worker.py",
    "--env", $envName
)

if ($env:POSTGRES_DSN) {
    $validationArgs += @("--postgres-dsn", $env:POSTGRES_DSN)
}

$scheduler = $null
$validator = $null

try {
    Write-Host "Starting prediction scheduler: $symbol $resolution every $intervalMinutes minute(s)"
    $scheduler = Start-Process -FilePath $python -ArgumentList $schedulerArgs -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -PassThru

    Write-Host "Starting validation worker"
    $validator = Start-Process -FilePath $python -ArgumentList $validationArgs -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -PassThru

    Write-Host "Starting dashboard at http://127.0.0.1:8765"
    & $python "src\dashboard_server.py" --host 127.0.0.1 --port 8765
}
finally {
    Write-Host ""
    Write-Host "Stopping background workers..."
    foreach ($process in @($scheduler, $validator)) {
        if ($null -ne $process) {
            try {
                $running = Get-Process -Id $process.Id -ErrorAction SilentlyContinue
                if ($null -ne $running) {
                    Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
                    Wait-Process -Id $process.Id -Timeout 5 -ErrorAction SilentlyContinue
                }
            }
            catch {
                Write-Warning "Could not stop process $($process.Id): $($_.Exception.Message)"
            }
        }
    }
    Write-Host "Dashboard and workers stopped."
}
