$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

function Import-DotEnv {
    param(
        [string]$Path = (Join-Path $PSScriptRoot ".env")
    )
    if (-not (Test-Path $Path)) {
        return
    }
    foreach ($rawLine in Get-Content $Path) {
        $line = $rawLine.Trim()
        if ([string]::IsNullOrWhiteSpace($line) -or $line.StartsWith("#") -or -not $line.Contains("=")) {
            continue
        }
        $parts = $line.Split("=", 2)
        $key = $parts[0].Trim()
        $value = $parts[1].Trim().Trim('"').Trim("'")
        if ($key -and -not [Environment]::GetEnvironmentVariable($key, "Process")) {
            [Environment]::SetEnvironmentVariable($key, $value, "Process")
        }
    }
}

function Get-ResolutionMinutes {
    param(
        [string]$Resolution
    )
    switch ($Resolution.ToUpper()) {
        "MINUTE" { return 1 }
        "MINUTE_5" { return 5 }
        "MINUTE_15" { return 15 }
        "MINUTE_30" { return 30 }
        "HOUR" { return 60 }
        "HOUR_4" { return 240 }
        "DAY" { return 1440 }
        "WEEK" { return 10080 }
        default { return 5 }
    }
}

Import-DotEnv

$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
$symbol = if ($env:SIGNAL_SYMBOL) { $env:SIGNAL_SYMBOL } else { "ETHUSD" }
$market = if ($env:CAPITAL_DEFAULT_MARKET_SEARCH) { $env:CAPITAL_DEFAULT_MARKET_SEARCH } else { "ETHUSD" }
$resolution = if ($env:SIGNAL_RESOLUTION) { $env:SIGNAL_RESOLUTION } elseif ($env:CAPITAL_DEFAULT_RESOLUTION) { $env:CAPITAL_DEFAULT_RESOLUTION } else { "MINUTE_5" }
$streamResolution = if ($env:LIVE_PRICE_RESOLUTION) { $env:LIVE_PRICE_RESOLUTION } else { $resolution }
$autoFinetuneResolution = if ($env:AUTO_FINETUNE_RESOLUTION) { $env:AUTO_FINETUNE_RESOLUTION } else { "MINUTE_5" }
$historicalBackfillResolution = if ($env:HISTORICAL_BACKFILL_RESOLUTION) { $env:HISTORICAL_BACKFILL_RESOLUTION } else { "MINUTE_5" }
$intervalMinutes = if ($env:SIGNAL_INTERVAL_MINUTES) { $env:SIGNAL_INTERVAL_MINUTES } else { [string](Get-ResolutionMinutes -Resolution $resolution) }
$autoFinetuneIntervalMinutes = if ($env:AUTO_FINETUNE_INTERVAL_MINUTES) { $env:AUTO_FINETUNE_INTERVAL_MINUTES } else { [string](Get-ResolutionMinutes -Resolution $autoFinetuneResolution) }
$historicalBackfillEnabled = if ($env:ENABLE_HISTORICAL_5M_BACKFILL) { $env:ENABLE_HISTORICAL_5M_BACKFILL } else { "true" }
$historicalBackfillDays = if ($env:HISTORICAL_BACKFILL_DAYS) { $env:HISTORICAL_BACKFILL_DAYS } else { "35" }
$historicalBackfillIntervalMinutes = if ($env:HISTORICAL_BACKFILL_INTERVAL_MINUTES) { $env:HISTORICAL_BACKFILL_INTERVAL_MINUTES } else { "5" }
$autoFinetuneEnabled = if ($env:ENABLE_AUTO_FINETUNE) { $env:ENABLE_AUTO_FINETUNE } else { "true" }
$maintenanceEnabled = if ($env:ENABLE_MAINTENANCE_WORKER) { $env:ENABLE_MAINTENANCE_WORKER } else { "true" }
$envName = if ($env:CAPITAL_ENV) { $env:CAPITAL_ENV } else { "demo" }
[int]$restartMaxAttempts = if ($env:WORKER_RESTART_MAX_ATTEMPTS) { $env:WORKER_RESTART_MAX_ATTEMPTS } else { 20 }
[int]$monitorIntervalSeconds = if ($env:WORKER_MONITOR_INTERVAL_SECONDS) { $env:WORKER_MONITOR_INTERVAL_SECONDS } else { 5 }
[int]$dashboardRestartMaxAttempts = if ($env:DASHBOARD_RESTART_MAX_ATTEMPTS) { $env:DASHBOARD_RESTART_MAX_ATTEMPTS } else { 20 }
$cleanupStaleProcessesOnStart = if ($env:CLEANUP_STALE_PROCESSES_ON_START) { $env:CLEANUP_STALE_PROCESSES_ON_START } else { "true" }

$outputDir = Join-Path $PSScriptRoot "output"
$logsDir = Join-Path $outputDir "logs"
$dashboardStdOutLog = Join-Path $logsDir "dashboard_stdout.log"
$dashboardStdErrLog = Join-Path $logsDir "dashboard_stderr.log"
$managedScriptPatterns = @(
    "src\main_prediction_scheduler.py",
    "src\main_validation_worker.py",
    "src\main_stream_ohlc.py",
    "src\main_auto_finetune_worker.py",
    "src\main_maintenance_worker.py",
    "src\dashboard_server.py"
)
$script:processJobHandle = [IntPtr]::Zero

function Test-FlagEnabled {
    param(
        [string]$Value,
        [bool]$Default = $false
    )
    if ([string]::IsNullOrWhiteSpace($Value)) {
        return $Default
    }
    return ($Value.Trim().ToLower() -in @("1", "true", "yes", "on"))
}

function Initialize-ProcessJob {
    if ($script:processJobHandle -ne [IntPtr]::Zero) {
        return
    }
    if (-not ("ProcessJobHelper" -as [type])) {
        Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;

public static class ProcessJobHelper
{
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern IntPtr CreateJobObject(IntPtr lpJobAttributes, string lpName);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool SetInformationJobObject(IntPtr hJob, int JobObjectInfoClass, IntPtr lpJobObjectInfo, uint cbJobObjectInfoLength);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool AssignProcessToJobObject(IntPtr hJob, IntPtr hProcess);

    private const int JobObjectExtendedLimitInformation = 9;
    private const uint JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000;

    [StructLayout(LayoutKind.Sequential)]
    private struct JOBOBJECT_BASIC_LIMIT_INFORMATION
    {
        public long PerProcessUserTimeLimit;
        public long PerJobUserTimeLimit;
        public uint LimitFlags;
        public UIntPtr MinimumWorkingSetSize;
        public UIntPtr MaximumWorkingSetSize;
        public uint ActiveProcessLimit;
        public IntPtr Affinity;
        public uint PriorityClass;
        public uint SchedulingClass;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct IO_COUNTERS
    {
        public ulong ReadOperationCount;
        public ulong WriteOperationCount;
        public ulong OtherOperationCount;
        public ulong ReadTransferCount;
        public ulong WriteTransferCount;
        public ulong OtherTransferCount;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct JOBOBJECT_EXTENDED_LIMIT_INFORMATION
    {
        public JOBOBJECT_BASIC_LIMIT_INFORMATION BasicLimitInformation;
        public IO_COUNTERS IoInfo;
        public UIntPtr ProcessMemoryLimit;
        public UIntPtr JobMemoryLimit;
        public UIntPtr PeakProcessMemoryUsed;
        public UIntPtr PeakJobMemoryUsed;
    }

    public static IntPtr CreateKillOnCloseJob()
    {
        IntPtr job = CreateJobObject(IntPtr.Zero, null);
        if (job == IntPtr.Zero)
        {
            throw new InvalidOperationException("CreateJobObject failed: " + Marshal.GetLastWin32Error());
        }

        JOBOBJECT_EXTENDED_LIMIT_INFORMATION info = new JOBOBJECT_EXTENDED_LIMIT_INFORMATION();
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
        int infoLength = Marshal.SizeOf(typeof(JOBOBJECT_EXTENDED_LIMIT_INFORMATION));
        IntPtr infoPtr = Marshal.AllocHGlobal(infoLength);
        try
        {
            Marshal.StructureToPtr(info, infoPtr, false);
            if (!SetInformationJobObject(job, JobObjectExtendedLimitInformation, infoPtr, (uint)infoLength))
            {
                throw new InvalidOperationException("SetInformationJobObject failed: " + Marshal.GetLastWin32Error());
            }
        }
        finally
        {
            Marshal.FreeHGlobal(infoPtr);
        }

        return job;
    }

    public static bool AddProcess(IntPtr jobHandle, IntPtr processHandle)
    {
        if (jobHandle == IntPtr.Zero || processHandle == IntPtr.Zero)
        {
            return false;
        }
        return AssignProcessToJobObject(jobHandle, processHandle);
    }
}
"@
    }

    try {
        $script:processJobHandle = [ProcessJobHelper]::CreateKillOnCloseJob()
    }
    catch {
        Write-Warning "Unable to initialize process lifetime guard: $($_.Exception.Message)"
        $script:processJobHandle = [IntPtr]::Zero
    }
}

function Add-ProcessToJob {
    param(
        [Parameter(Mandatory = $false)]
        $Process,
        [string]$Name = "process"
    )
    if ($null -eq $Process) {
        return
    }
    if ($script:processJobHandle -eq [IntPtr]::Zero) {
        return
    }
    try {
        $assigned = [ProcessJobHelper]::AddProcess($script:processJobHandle, $Process.Handle)
        if (-not $assigned) {
            Write-Warning "Unable to attach $Name ($($Process.Id)) to process lifetime guard."
        }
    }
    catch {
        Write-Warning "Failed to attach $Name ($($Process.Id)) to process lifetime guard: $($_.Exception.Message)"
    }
}

function Get-ManagedPythonProcesses {
    return Get-CimInstance Win32_Process -Filter "name='python.exe'" |
        Where-Object {
            $cmd = [string]($_.CommandLine)
            if ([string]::IsNullOrWhiteSpace($cmd)) {
                return $false
            }
            $cmdLower = $cmd.ToLower()
            foreach ($pattern in $managedScriptPatterns) {
                if ($cmdLower.Contains($pattern.ToLower())) {
                    return $true
                }
            }
            return $false
        }
}

function Stop-StaleManagedProcesses {
    $existing = @(Get-ManagedPythonProcesses)
    if (-not $existing.Count) {
        return
    }

    Write-Warning "Detected $($existing.Count) existing managed process(es). Stopping stale processes before startup."
    foreach ($proc in $existing) {
        try {
            Stop-Process -Id $proc.ProcessId -Force -ErrorAction SilentlyContinue
            Write-Host "Stopped stale managed process ($($proc.ProcessId))"
        }
        catch {
            Write-Warning "Could not stop stale managed process ($($proc.ProcessId)): $($_.Exception.Message)"
        }
    }
}

function Test-Preflight {
    if (-not (Test-Path $python)) {
        throw "Python virtual environment executable not found: $python"
    }

    New-Item -ItemType Directory -Path $outputDir -Force | Out-Null
    New-Item -ItemType Directory -Path $logsDir -Force | Out-Null

    Write-Host "Preflight check"
    Write-Host "  Python: $python"
    Write-Host "  Symbol: $symbol"
    Write-Host "  Resolution: $resolution"
    Write-Host "  Stream resolution: $streamResolution"
    Write-Host "  Auto finetune resolution: $autoFinetuneResolution"
    Write-Host "  Historical backfill resolution: $historicalBackfillResolution"
    Write-Host "  Historical backfill days: $historicalBackfillDays"
    Write-Host "  Environment: $envName"
    Write-Host "  Auto finetune: $autoFinetuneEnabled"
    Write-Host "  Maintenance worker: $maintenanceEnabled"
    Write-Host "  Restart max attempts: $restartMaxAttempts"
    Write-Host "  Dashboard restart max attempts: $dashboardRestartMaxAttempts"
    Write-Host "  Monitor interval (seconds): $monitorIntervalSeconds"
    Write-Host "  Cleanup stale processes on start: $(Test-FlagEnabled -Value $cleanupStaleProcessesOnStart -Default $true)"
    if ($env:POSTGRES_DSN) {
        Write-Host "  PostgreSQL DSN: configured"
    }
    else {
        Write-Warning "POSTGRES_DSN is not set. PostgreSQL-backed features and heartbeats may be unavailable."
    }

    & $python -c "import sys; print(sys.version)"
    if ($LASTEXITCODE -ne 0) {
        throw "Python preflight execution failed with exit code $LASTEXITCODE"
    }
}

function New-Worker {
    param(
        [string]$Name,
        [string[]]$LaunchParams,
        [bool]$Enabled
    )
    return [PSCustomObject]@{
        Name = $Name
        LaunchParams = $LaunchParams
        Enabled = $Enabled
        Process = $null
        RestartCount = 0
    }
}

function Start-Worker {
    param(
        [Parameter(Mandatory = $true)]
        $Worker
    )
    if (-not $Worker.Enabled) {
        return
    }
    Write-Host "Starting worker $($Worker.Name)"
    $Worker.Process = Start-Process -FilePath $python -ArgumentList $Worker.LaunchParams -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -PassThru
    Add-ProcessToJob -Process $Worker.Process -Name $Worker.Name
}

function Start-Dashboard {
    Write-Host "Starting dashboard at http://127.0.0.1:8765"
    Write-Host "  stdout log: $dashboardStdOutLog"
    Write-Host "  stderr log: $dashboardStdErrLog"
    $dashboardProc = Start-Process -FilePath $python -ArgumentList @("-u", "src\dashboard_server.py", "--host", "127.0.0.1", "--port", "8765") -WorkingDirectory $PSScriptRoot -PassThru -RedirectStandardOutput $dashboardStdOutLog -RedirectStandardError $dashboardStdErrLog
    Add-ProcessToJob -Process $dashboardProc -Name "dashboard"
    return $dashboardProc
}

function Stop-TrackedProcess {
    param(
        [Parameter(Mandatory = $false)]
        $Process,
        [string]$Name = "process"
    )
    if ($null -eq $Process) {
        return
    }
    try {
        $running = Get-Process -Id $Process.Id -ErrorAction SilentlyContinue
        if ($null -ne $running) {
            Stop-Process -Id $Process.Id -Force -ErrorAction SilentlyContinue
            Wait-Process -Id $Process.Id -Timeout 5 -ErrorAction SilentlyContinue
            Write-Host "Stopped $Name ($($Process.Id))"
        }
    }
    catch {
        Write-Warning "Could not stop $Name ($($Process.Id)): $($_.Exception.Message)"
    }
}

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

$streamArgs = @(
    "src\main_stream_ohlc.py",
    "--market", $market,
    "--resolution", $streamResolution,
    "--env", $envName,
    "--symbol", $symbol
)

$autoFinetuneArgs = @(
    "src\main_auto_finetune_worker.py",
    "--symbol", $symbol,
    "--resolution", $autoFinetuneResolution,
    "--poll-minutes", $autoFinetuneIntervalMinutes,
    "--env", $envName
)

$maintenanceArgs = @(
    "src\main_maintenance_worker.py",
    "--market", $market,
    "--symbol", $symbol,
    "--resolution", $historicalBackfillResolution,
    "--historical-backfill-days", $historicalBackfillDays,
    "--historical-backfill-interval-minutes", $historicalBackfillIntervalMinutes,
    "--env", $envName
)

if (-not (Test-FlagEnabled -Value $historicalBackfillEnabled -Default $true)) {
    $maintenanceArgs += @("--disable-historical-backfill")
}

if ($env:POSTGRES_DSN) {
    $validationArgs += @("--postgres-dsn", $env:POSTGRES_DSN)
    $streamArgs += @("--postgres-dsn", $env:POSTGRES_DSN)
    $autoFinetuneArgs += @("--postgres-dsn", $env:POSTGRES_DSN)
    $maintenanceArgs += @("--postgres-dsn", $env:POSTGRES_DSN)
}

if ($env:KRONOS_FINETUNE_COMMAND) {
    $autoFinetuneArgs += @("--command", $env:KRONOS_FINETUNE_COMMAND)
}

$workers = @(
    (New-Worker -Name "prediction_scheduler" -LaunchParams $schedulerArgs -Enabled $true),
    (New-Worker -Name "validation_worker" -LaunchParams $validationArgs -Enabled $true),
    (New-Worker -Name "websocket_stream" -LaunchParams $streamArgs -Enabled $true),
    (New-Worker -Name "auto_finetune_worker" -LaunchParams $autoFinetuneArgs -Enabled ($autoFinetuneEnabled.ToLower() -in @("1", "true", "yes"))),
    (New-Worker -Name "maintenance_worker" -LaunchParams $maintenanceArgs -Enabled ($maintenanceEnabled.ToLower() -in @("1", "true", "yes")))
)

$dashboard = $null

try {
    Test-Preflight
    Initialize-ProcessJob

    if (Test-FlagEnabled -Value $cleanupStaleProcessesOnStart -Default $true) {
        Stop-StaleManagedProcesses
    }

    Write-Host "Applying database migrations"
    $migrateArgs = @("src\main_db_migrate.py")
    if ($env:POSTGRES_DSN) {
        $migrateArgs += @("--dsn", $env:POSTGRES_DSN)
    }
    & $python @migrateArgs
    if ($LASTEXITCODE -ne 0) {
        throw "Database migration failed with exit code $LASTEXITCODE"
    }

    if (Test-FlagEnabled -Value $historicalBackfillEnabled -Default $true) {
        Write-Host "Backfilling and gap-filling $historicalBackfillDays day(s) of 5-minute Capital.com candles"
        $backfillArgs = @(
            "src\main_backfill_historical_5m.py",
            "--market", $market,
            "--symbol", $symbol,
            "--resolution", $historicalBackfillResolution,
            "--days", $historicalBackfillDays,
            "--env", $envName
        )
        if ($env:POSTGRES_DSN) {
            $backfillArgs += @("--postgres-dsn", $env:POSTGRES_DSN)
        }
        & $python @backfillArgs
        if ($LASTEXITCODE -ne 0) {
            Write-Warning "Historical 5m backfill failed with exit code $LASTEXITCODE. The maintenance worker will retry automatically."
        }
    }

    Write-Host "Starting managed workers"
    foreach ($worker in $workers) {
        if ($worker.Enabled) {
            Start-Worker -Worker $worker
        }
    }

    $dashboardRestartCount = 0
    $dashboard = Start-Dashboard
    Write-Host "Dashboard PID: $($dashboard.Id)"
    Write-Host "Supervisor is active. Press Ctrl+C to stop dashboard and workers."

    while ($true) {
        Start-Sleep -Seconds $monitorIntervalSeconds

        $dashboardRunning = Get-Process -Id $dashboard.Id -ErrorAction SilentlyContinue
        if ($null -eq $dashboardRunning) {
            $dashboardRestartCount += 1
            if ($dashboardRestartCount -gt $dashboardRestartMaxAttempts) {
                Write-Warning "Dashboard process exited and exceeded restart limit ($dashboardRestartMaxAttempts). Stopping supervisor."
                break
            }
            Write-Warning "Dashboard process exited unexpectedly. Restarting ($dashboardRestartCount/$dashboardRestartMaxAttempts)."
            $dashboard = Start-Dashboard
            Write-Host "Dashboard PID: $($dashboard.Id)"
            continue
        }

        foreach ($worker in $workers | Where-Object { $_.Enabled }) {
            if ($null -eq $worker.Process) {
                continue
            }
            $running = Get-Process -Id $worker.Process.Id -ErrorAction SilentlyContinue
            if ($null -eq $running) {
                $worker.RestartCount += 1
                if ($worker.RestartCount -gt $restartMaxAttempts) {
                    Write-Warning "Worker $($worker.Name) exceeded restart limit ($restartMaxAttempts). Leaving it stopped."
                    $worker.Enabled = $false
                    continue
                }
                Write-Warning "Worker $($worker.Name) exited unexpectedly. Restarting ($($worker.RestartCount)/$restartMaxAttempts)."
                Start-Worker -Worker $worker
            }
        }
    }
}
finally {
    Write-Host ""
    Write-Host "Stopping dashboard and workers..."
    Stop-TrackedProcess -Process $dashboard -Name "dashboard"
    foreach ($worker in $workers) {
        Stop-TrackedProcess -Process $worker.Process -Name $worker.Name
    }
    Write-Host "Dashboard and workers stopped."
}
