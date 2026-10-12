param([switch]$StopDatabase)
$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$runtime = Join-Path $repo '.runtime'
$pidFile = Join-Path $runtime 'services.json'

function Stop-OwnedTree([int]$ServiceId) {
    $children = Get-CimInstance Win32_Process -Filter "ParentProcessId=$ServiceId" -ErrorAction SilentlyContinue
    foreach ($child in $children) { Stop-OwnedTree $child.ProcessId }
    Stop-Process -Id $ServiceId -ErrorAction SilentlyContinue
}
if (Test-Path $pidFile) {
    $services = @(Get-Content -LiteralPath $pidFile -Raw | ConvertFrom-Json)
    foreach ($service in $services) {
        $process = Get-Process -Id $service.id -ErrorAction SilentlyContinue
        # PID reuse must never terminate an unrelated process.
        $expectedStart = [datetime]$service.started
        if ($process -and $process.StartTime.ToUniversalTime().Ticks -eq $expectedStart.ToUniversalTime().Ticks) {
            Stop-OwnedTree $process.Id
            Write-Host "Stopped $($service.name)"
        }
    }
    Remove-Item -LiteralPath $pidFile
}
if ($StopDatabase) {
    $data = Join-Path $runtime 'postgres'
    if (Test-Path (Join-Path $data 'PG_VERSION')) {
        & pg_ctl.exe -D $data -m fast -w stop
        if ($LASTEXITCODE -ne 0) { throw 'PostgreSQL could not be stopped; inspect .runtime/postgres.log' }
    }
}
