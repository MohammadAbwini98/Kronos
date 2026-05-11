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
        if ($key) {
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
$autoFinetuneEnabled = if ($env:ENABLE_AUTO_FINETUNE) { $env:ENABLE_AUTO_FINETUNE } else { "false" }
$maintenanceEnabled = if ($env:ENABLE_MAINTENANCE_WORKER) { $env:ENABLE_MAINTENANCE_WORKER } else { "true" }
$tradeExecutionEnabled = if ($env:ENABLE_TRADE_EXECUTION_WORKER) { $env:ENABLE_TRADE_EXECUTION_WORKER } elseif ($env:AUTO_EXECUTE_SIGNALS) { $env:AUTO_EXECUTE_SIGNALS } else { "false" }
$envName = if ($env:CAPITAL_ENV) { $env:CAPITAL_ENV } else { "demo" }
[int]$restartMaxAttempts = if ($env:WORKER_RESTART_MAX_ATTEMPTS) { $env:WORKER_RESTART_MAX_ATTEMPTS } else { 20 }
[int]$monitorIntervalSeconds = if ($env:WORKER_MONITOR_INTERVAL_SECONDS) { $env:WORKER_MONITOR_INTERVAL_SECONDS } else { 5 }
[int]$dashboardRestartMaxAttempts = if ($env:DASHBOARD_RESTART_MAX_ATTEMPTS) { $env:DASHBOARD_RESTART_MAX_ATTEMPTS } else { 20 }
$cleanupStaleProcessesOnStart = if ($env:CLEANUP_STALE_PROCESSES_ON_START) { $env:CLEANUP_STALE_PROCESSES_ON_START } else { "true" }
$supervisorInstanceId = if ($env:SUPERVISOR_INSTANCE_ID) { $env:SUPERVISOR_INSTANCE_ID } else { [guid]::NewGuid().ToString() }
$env:SUPERVISOR_INSTANCE_ID = $supervisorInstanceId
$allowDuplicateWorkers = if ($env:ALLOW_DUPLICATE_WORKERS) { $env:ALLOW_DUPLICATE_WORKERS } else { "false" }
[int]$supervisorLeaseTtlSeconds = if ($env:SUPERVISOR_LEASE_TTL_SECONDS) { $env:SUPERVISOR_LEASE_TTL_SECONDS } else { 120 }

$outputDir = Join-Path $PSScriptRoot "output"
$logsDir = Join-Path $outputDir "logs"
$dashboardStdOutLog = Join-Path $logsDir "dashboard_stdout.log"
$dashboardStdErrLog = Join-Path $logsDir "dashboard_stderr.log"
$managedScriptPatterns = @(
    "src/main_prediction_scheduler.py",
    "src/main_validation_worker.py",
    "src/main_stream_ohlc.py",
    "src/main_auto_finetune_worker.py",
    "src/main_maintenance_worker.py",
    "src/main_trade_execution_worker.py",
    "src/dashboard_server.py"
)
$script:processJobHandle = [IntPtr]::Zero
$defaultPostgresDsn = "postgresql://capital_kronos:capital_kronos@localhost:5432/capital_kronos"
$legacyLocalPostgresDsn = "postgresql://postgres:123@localhost:5432/capital_kronos"

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
    try {
        return Get-CimInstance Win32_Process -Filter "name='python.exe'" -ErrorAction Stop |
            Where-Object {
                $cmd = [string]($_.CommandLine)
                if ([string]::IsNullOrWhiteSpace($cmd)) {
                    return $false
                }
                $cmdLower = $cmd.ToLower().Replace("\", "/")
                foreach ($pattern in $managedScriptPatterns) {
                    if ($cmdLower.Contains($pattern.ToLower().Replace("\", "/"))) {
                        return $true
                    }
                }
                return $false
            }
    }
    catch {
        Write-Warning "Unable to inspect existing Python command lines for stale managed workers: $($_.Exception.Message). Continuing without startup cleanup."
        return @()
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
    if ($env:SSLKEYLOGFILE) {
        $workspaceSslKeyLog = Join-Path $logsDir "ssl-keys.log"
        try {
            $stream = [System.IO.File]::Open($workspaceSslKeyLog, [System.IO.FileMode]::Append, [System.IO.FileAccess]::Write, [System.IO.FileShare]::ReadWrite)
            $stream.Close()
            $env:SSLKEYLOGFILE = $workspaceSslKeyLog
        }
        catch {
            Write-Warning "Unable to prepare workspace SSLKEYLOGFILE at ${workspaceSslKeyLog}: $($_.Exception.Message). Clearing SSLKEYLOGFILE for worker startup."
            Remove-Item Env:SSLKEYLOGFILE -ErrorAction SilentlyContinue
        }
    }

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
    Write-Host "  Trade execution worker: $tradeExecutionEnabled"
    Write-Host "  Restart max attempts: $restartMaxAttempts"
    Write-Host "  Dashboard restart max attempts: $dashboardRestartMaxAttempts"
    Write-Host "  Monitor interval (seconds): $monitorIntervalSeconds"
    Write-Host "  Cleanup stale processes on start: $(Test-FlagEnabled -Value $cleanupStaleProcessesOnStart -Default $true)"
    Write-Host "  Supervisor instance: $supervisorInstanceId"
    Write-Host "  Allow duplicate workers: $(Test-FlagEnabled -Value $allowDuplicateWorkers -Default $false)"
    if ($env:SSLKEYLOGFILE) {
        Write-Host "  SSL key log file: $env:SSLKEYLOGFILE"
    }
    if ($env:POSTGRES_DSN) {
        Write-Host "  PostgreSQL DSN: configured"
    }
    else {
        Write-Warning "POSTGRES_DSN is not set. Startup will probe local DSN defaults during migration."
    }

    & $python -c "import sys; print(sys.version)"
    if ($LASTEXITCODE -ne 0) {
        throw "Python preflight execution failed with exit code $LASTEXITCODE"
    }
}

function Invoke-DatabaseMigrations {
    $candidateDsns = @()
    $configuredDsn = [Environment]::GetEnvironmentVariable("POSTGRES_DSN", "Process")

    if (-not [string]::IsNullOrWhiteSpace($configuredDsn)) {
        $candidateDsns = @($configuredDsn)
    }
    else {
        $candidateDsns = @($defaultPostgresDsn, $legacyLocalPostgresDsn)
    }

    $lastMigrationExitCode = 0

    for ($index = 0; $index -lt $candidateDsns.Count; $index++) {
        $dsnCandidate = $candidateDsns[$index]
        $migrateArgs = @("src\main_db_migrate.py", "--dsn", $dsnCandidate)

        & $python @migrateArgs
        $exitCode = $LASTEXITCODE

        if ($exitCode -eq 0) {
            if ($env:POSTGRES_DSN -ne $dsnCandidate) {
                $env:POSTGRES_DSN = $dsnCandidate
            }
            if ([string]::IsNullOrWhiteSpace($configuredDsn) -and $index -gt 0) {
                Write-Warning "Using fallback local PostgreSQL DSN for startup. Set POSTGRES_DSN in your environment to avoid probing on future runs."
            }
            return
        }

        $lastMigrationExitCode = $exitCode
        if ([string]::IsNullOrWhiteSpace($configuredDsn) -and $index -lt ($candidateDsns.Count - 1)) {
            Write-Warning "Migration failed with detected default DSN. Retrying with fallback local DSN."
        }
    }

    if (-not [string]::IsNullOrWhiteSpace($configuredDsn)) {
        throw "Database migration failed with exit code $lastMigrationExitCode using configured POSTGRES_DSN."
    }
    throw "Database migration failed with exit code $lastMigrationExitCode after trying default local DSNs. Set POSTGRES_DSN explicitly for your environment."
}

function Get-CommandOutputText {
    param(
        $Output
    )
    if ($null -eq $Output) {
        return ""
    }
    return ([string]::Join("`n", @($Output))).Trim()
}

function Get-LocalHostNames {
    $hosts = @()
    if (-not [string]::IsNullOrWhiteSpace($env:COMPUTERNAME)) {
        $hosts += $env:COMPUTERNAME
    }
    try {
        $dnsHost = [System.Net.Dns]::GetHostName()
        if (-not [string]::IsNullOrWhiteSpace($dnsHost)) {
            $hosts += $dnsHost
        }
    }
    catch {
        # Ignore DNS hostname lookup failures in local-only fallback logic.
    }
    return @($hosts | ForEach-Object { $_.ToLowerInvariant() } | Select-Object -Unique)
}

function Invoke-SupervisorLeaseAcquire {
    param(
        [string]$InstanceId,
        [int]$ProcessId,
        [int]$TtlSeconds,
        [bool]$AllowDuplicate
    )

    $leaseArgs = @(
        "src\main_supervisor_lease.py",
        "acquire",
        "--instance-id", $InstanceId,
        "--process-id", "$ProcessId",
        "--command-line", "start_dashboard.ps1",
        "--ttl-seconds", "$TtlSeconds"
    )
    if ($AllowDuplicate) {
        $leaseArgs += "--allow-duplicate"
    }
    if ($env:POSTGRES_DSN) {
        $leaseArgs += @("--dsn", $env:POSTGRES_DSN)
    }

    $leaseOutput = & $python @leaseArgs
    $leaseExitCode = $LASTEXITCODE
    $leaseText = Get-CommandOutputText -Output $leaseOutput
    if (-not [string]::IsNullOrWhiteSpace($leaseText)) {
        Write-Host $leaseText
    }
    if ($leaseExitCode -eq 0) {
        return
    }

    $leasePayload = $null
    if (-not [string]::IsNullOrWhiteSpace($leaseText)) {
        try {
            $leasePayload = $leaseText | ConvertFrom-Json -ErrorAction Stop
        }
        catch {
            $leasePayload = $null
        }
    }

    if ($null -ne $leasePayload -and $null -ne $leasePayload.existing -and -not $AllowDuplicate) {
        $existing = $leasePayload.existing
        $existingHost = [string]$existing.host_name
        $existingInstanceId = [string]$existing.supervisor_instance_id
        $existingProcessId = 0
        [void][int]::TryParse([string]$existing.process_id, [ref]$existingProcessId)
        $localHosts = Get-LocalHostNames
        $isLocalLease = $false
        if (-not [string]::IsNullOrWhiteSpace($existingHost)) {
            $isLocalLease = ($localHosts -contains $existingHost.ToLowerInvariant())
        }
        $existingProcess = $null
        if ($existingProcessId -gt 0) {
            $existingProcess = Get-Process -Id $existingProcessId -ErrorAction SilentlyContinue
        }

        if ($isLocalLease -and $null -eq $existingProcess -and -not [string]::IsNullOrWhiteSpace($existingInstanceId)) {
            Write-Warning "Detected stale local supervisor lease for non-running process $existingProcessId. Releasing and retrying acquire."
            $releaseArgs = @(
                "src\main_supervisor_lease.py",
                "release",
                "--instance-id", $existingInstanceId
            )
            if ($env:POSTGRES_DSN) {
                $releaseArgs += @("--dsn", $env:POSTGRES_DSN)
            }

            $releaseOutput = & $python @releaseArgs
            $releaseExitCode = $LASTEXITCODE
            $releaseText = Get-CommandOutputText -Output $releaseOutput
            if (-not [string]::IsNullOrWhiteSpace($releaseText)) {
                Write-Host $releaseText
            }

            if ($releaseExitCode -eq 0) {
                $retryOutput = & $python @leaseArgs
                $retryExitCode = $LASTEXITCODE
                $retryText = Get-CommandOutputText -Output $retryOutput
                if (-not [string]::IsNullOrWhiteSpace($retryText)) {
                    Write-Host $retryText
                }
                if ($retryExitCode -eq 0) {
                    return
                }
            }
            throw "Failed to reacquire supervisor lease after releasing stale local lease."
        }

        $details = @()
        if (-not [string]::IsNullOrWhiteSpace($existingHost)) {
            $details += "host=$existingHost"
        }
        if ($existingProcessId -gt 0) {
            $details += "pid=$existingProcessId"
        }
        if (-not [string]::IsNullOrWhiteSpace([string]$existing.expires_at)) {
            $details += "expires_at=$($existing.expires_at)"
        }
        $detailText = if ($details.Count -gt 0) { " ($($details -join ', '))" } else { "" }
        throw "Another active dashboard supervisor lease exists$detailText. Set ALLOW_DUPLICATE_WORKERS=true to override intentionally."
    }

    throw "Another active dashboard supervisor lease exists. Set ALLOW_DUPLICATE_WORKERS=true to override intentionally."
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

function Join-ProcessArguments {
    param(
        [string[]]$Arguments
    )
    $quoted = foreach ($arg in $Arguments) {
        if ($null -eq $arg) {
            '""'
            continue
        }
        $text = [string]$arg
        if ($text -notmatch '[\s"]') {
            $text
            continue
        }
        $builder = New-Object System.Text.StringBuilder
        [void]$builder.Append('"')
        $backslashes = 0
        foreach ($char in $text.ToCharArray()) {
            if ($char -eq '\') {
                $backslashes += 1
                continue
            }
            if ($char -eq '"') {
                [void]$builder.Append(('\' * (($backslashes * 2) + 1)))
                [void]$builder.Append('"')
                $backslashes = 0
                continue
            }
            if ($backslashes -gt 0) {
                [void]$builder.Append(('\' * $backslashes))
                $backslashes = 0
            }
            [void]$builder.Append($char)
        }
        if ($backslashes -gt 0) {
            [void]$builder.Append(('\' * ($backslashes * 2)))
        }
        [void]$builder.Append('"')
        $builder.ToString()
    }
    return ($quoted -join " ")
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
    $workerStdOutLog = Join-Path $logsDir "$($Worker.Name)_stdout.log"
    $workerStdErrLog = Join-Path $logsDir "$($Worker.Name)_stderr.log"
    $argumentLine = Join-ProcessArguments -Arguments $Worker.LaunchParams
    $Worker.Process = Start-Process -FilePath $python -ArgumentList $argumentLine -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput $workerStdOutLog -RedirectStandardError $workerStdErrLog
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

function Invoke-SupervisorLeaseReleaseQuietly {
    param(
        [string]$InstanceId
    )

    $releaseArgs = @(
        "src\main_supervisor_lease.py",
        "release",
        "--instance-id", $InstanceId
    )
    if ($env:POSTGRES_DSN) {
        $releaseArgs += @("--dsn", $env:POSTGRES_DSN)
    }

    $releaseStdOutLog = Join-Path $logsDir "supervisor_lease_release_stdout.log"
    $releaseStdErrLog = Join-Path $logsDir "supervisor_lease_release_stderr.log"
    try {
        $argumentLine = Join-ProcessArguments -Arguments $releaseArgs
        $releaseProc = Start-Process -FilePath $python -ArgumentList $argumentLine -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput $releaseStdOutLog -RedirectStandardError $releaseStdErrLog
        $exited = $releaseProc.WaitForExit(5000)
        if (-not $exited) {
            Stop-Process -Id $releaseProc.Id -Force -ErrorAction SilentlyContinue
            Write-Warning "Supervisor lease release timed out; stale lease cleanup will run on the next startup."
            return
        }
        if ($releaseProc.ExitCode -ne 0) {
            Write-Warning "Supervisor lease release exited with code $($releaseProc.ExitCode); see $releaseStdErrLog."
        }
    }
    catch {
        Write-Warning "Supervisor lease release failed during shutdown: $($_.Exception.Message)"
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

$tradeExecutionArgs = @(
    "src\main_trade_execution_worker.py"
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
    (New-Worker -Name "maintenance_worker" -LaunchParams $maintenanceArgs -Enabled ($maintenanceEnabled.ToLower() -in @("1", "true", "yes"))),
    (New-Worker -Name "trade_execution_worker" -LaunchParams $tradeExecutionArgs -Enabled ($tradeExecutionEnabled.ToLower() -in @("1", "true", "yes")))
)

$dashboard = $null

try {
    Test-Preflight
    Initialize-ProcessJob

    if (Test-FlagEnabled -Value $cleanupStaleProcessesOnStart -Default $true) {
        Stop-StaleManagedProcesses
    }

    Write-Host "Applying database migrations"
    Invoke-DatabaseMigrations

    Write-Host "Acquiring supervisor lease"
    Invoke-SupervisorLeaseAcquire -InstanceId $supervisorInstanceId -ProcessId $PID -TtlSeconds $supervisorLeaseTtlSeconds -AllowDuplicate (Test-FlagEnabled -Value $allowDuplicateWorkers -Default $false)

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

        $heartbeatArgs = @(
            "src\main_supervisor_lease.py",
            "heartbeat",
            "--instance-id", $supervisorInstanceId,
            "--ttl-seconds", "$supervisorLeaseTtlSeconds"
        )
        if ($env:POSTGRES_DSN) {
            $heartbeatArgs += @("--dsn", $env:POSTGRES_DSN)
        }
        & $python @heartbeatArgs | Out-Null
        if ($LASTEXITCODE -ne 0) {
            Write-Warning "Supervisor lease heartbeat failed. Continuing process monitor loop."
        }

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
    Invoke-SupervisorLeaseReleaseQuietly -InstanceId $supervisorInstanceId
    Write-Host "Dashboard and workers stopped."
}
