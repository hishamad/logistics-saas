param([switch]$SkipInstall, [switch]$ExternalDatabase, [switch]$ProductionWeb)
$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$backend = Join-Path $repo 'backend'
$web = Join-Path $repo 'apps/web'
$runtime = Join-Path $repo '.runtime'
New-Item -ItemType Directory -Path $runtime -Force | Out-Null

foreach ($port in @(8000, 3000)) {
    if (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue) {
        throw "Port $port is already in use. Stop the existing service before starting another demo."
    }
}
if (!(Test-Path (Join-Path $backend '.env'))) {
    Copy-Item -LiteralPath (Join-Path $backend '.env.example') -Destination (Join-Path $backend '.env')
}
if (!$SkipInstall) {
    Push-Location $backend
    try { & uv sync --python 3.13; if ($LASTEXITCODE -ne 0) { throw 'Backend dependency installation failed' } }
    finally { Pop-Location }
    Push-Location $web
    try { & npm.cmd ci; if ($LASTEXITCODE -ne 0) { throw 'Frontend dependency installation failed' } }
    finally { Pop-Location }
}
if (!$ExternalDatabase) {
    $data = Join-Path $runtime 'postgres'
    $pgctl = (Get-Command pg_ctl.exe -ErrorAction Stop).Source
    if (!(Test-Path (Join-Path $data 'PG_VERSION'))) {
        & initdb.exe -D $data -U freight --auth=trust --encoding=UTF8 --locale=C
        if ($LASTEXITCODE -ne 0) { throw 'Local PostgreSQL initialization failed' }
    }
    & $pgctl -D $data status *> $null
    if ($LASTEXITCODE -ne 0) {
        if (Get-NetTCPConnection -LocalPort 55432 -State Listen -ErrorAction SilentlyContinue) {
            throw 'Port 55432 belongs to another PostgreSQL service. Configure an external database instead.'
        }
        & $pgctl -D $data -l (Join-Path $runtime 'postgres.log') -o '-p 55432 -h 127.0.0.1' -w start
        if ($LASTEXITCODE -ne 0) { throw 'Local PostgreSQL startup failed' }
    }
    $exists = & psql.exe -h 127.0.0.1 -p 55432 -U freight -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='freight'"
    if ($LASTEXITCODE -ne 0) { throw 'Could not inspect local PostgreSQL' }
    if ($exists -ne '1') {
        & createdb.exe -h 127.0.0.1 -p 55432 -U freight freight
        if ($LASTEXITCODE -ne 0) { throw 'Local database creation failed' }
    }
}
$python = Join-Path $backend '.venv/Scripts/python.exe'
if (!(Test-Path $python)) { throw 'Run without -SkipInstall to install the backend first' }
Push-Location $backend
try { & $python scripts/run_local.py alembic upgrade head; if ($LASTEXITCODE -ne 0) { throw 'Database migration failed' } }
finally { Pop-Location }
if ($ProductionWeb) {
    Push-Location $web
    try { & npm.cmd run build; if ($LASTEXITCODE -ne 0) { throw 'Production frontend build failed' } }
    finally { Pop-Location }
}

$services = [System.Collections.Generic.List[object]]::new()
$pidFile = Join-Path $runtime 'services.json'
function Start-DemoService([string]$Name, [string]$Exe, [string[]]$Arguments, [string]$Directory) {
    $process = Start-Process -FilePath $Exe -ArgumentList $Arguments -WorkingDirectory $Directory -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $runtime "$Name.out.log") -RedirectStandardError (Join-Path $runtime "$Name.err.log")
    $services.Add(@{ name=$Name; id=$process.Id; started=$process.StartTime.ToUniversalTime().ToString('o'); executable=$Exe })
    $services | ConvertTo-Json -Depth 3 | Set-Content -LiteralPath $pidFile -Encoding utf8
}
try {
    Start-DemoService 'api' $python @('scripts/run_local.py','uvicorn','freight.api.app:app','--host','127.0.0.1','--port','8000','--no-proxy-headers','--no-access-log') $backend
    Start-DemoService 'worker' $python @('scripts/run_local.py','freight.workers.runner') $backend
    $webMode = if ($ProductionWeb) { 'start' } else { 'dev' }
    Start-DemoService 'web' (Get-Command node.exe -ErrorAction Stop).Source @('node_modules/next/dist/bin/next',$webMode,'--hostname','127.0.0.1','--port','3000') $web
    foreach ($url in @('http://127.0.0.1:8000/health','http://127.0.0.1:3000')) {
        $ready = $false
        for ($attempt=0; $attempt -lt 30; $attempt++) {
            try { $response = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 2; if ($response.StatusCode -eq 200) { $ready=$true; break } }
            catch { Start-Sleep -Milliseconds 300 }
        }
        if (!$ready) { throw "Service did not become ready: $url. Inspect .runtime/*.err.log." }
    }
    Write-Host 'Madar is ready: http://127.0.0.1:3000'
    Write-Host 'Local synthetic data only. Logs: .runtime. Stop: .\scripts\stop-demo.ps1'
} catch {
    & (Join-Path $PSScriptRoot 'stop-demo.ps1')
    throw
}
