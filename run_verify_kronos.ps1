param(
    [switch]$SmokeTest,
    [switch]$NoPause
)

$ErrorActionPreference = "Stop"
$RepoDir = "C:\AI\Kronos"
$VenvActivate = Join-Path $RepoDir ".venv\Scripts\Activate.ps1"
$VerifyScript = Join-Path $RepoDir "verify_kronos_local.py"

Write-Host "Kronos local verification"
Write-Host "Repository: $RepoDir"

if (-not (Test-Path $VenvActivate)) {
    throw "Virtual environment activation script not found: $VenvActivate"
}

if (-not (Test-Path $VerifyScript)) {
    throw "Verification script not found: $VerifyScript"
}

. $VenvActivate

$argsList = @($VerifyScript)
if ($SmokeTest) {
    $argsList += "--smoke-test"
}

python @argsList
$exitCode = $LASTEXITCODE

if ($exitCode -eq 0) {
    Write-Host "Verification finished successfully."
} else {
    Write-Host "Verification failed with exit code $exitCode."
}

if (-not $NoPause) {
    Write-Host "Press Enter to close..."
    [void][System.Console]::ReadLine()
}

exit $exitCode
