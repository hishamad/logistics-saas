$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
Push-Location (Join-Path $repo 'backend')
try {
    & uv run ruff format --check src tests scripts migrations
    if ($LASTEXITCODE -ne 0) { throw 'Python formatting failed' }
    & uv run ruff check src tests scripts migrations
    if ($LASTEXITCODE -ne 0) { throw 'Python lint failed' }
    & uv run mypy src
    if ($LASTEXITCODE -ne 0) { throw 'Python types failed' }
    if (!$env:FREIGHT_TEST_DATABASE_URL) { $env:FREIGHT_TEST_DATABASE_URL = 'postgresql+psycopg://freight:freight_local_only@127.0.0.1:55432/freight' }
    & uv run pytest -q
    if ($LASTEXITCODE -ne 0) { throw 'Backend tests failed' }
    & uv run python scripts/export_openapi.py
    if ($LASTEXITCODE -ne 0) { throw 'API export failed' }
} finally { Pop-Location }
Push-Location (Join-Path $repo 'apps/web')
try {
    & npm.cmd run api:generate
    if ($LASTEXITCODE -ne 0) { throw 'API types failed' }
    & npm.cmd run typecheck
    if ($LASTEXITCODE -ne 0) { throw 'Frontend types failed' }
    & npm.cmd run format:check
    if ($LASTEXITCODE -ne 0) { throw 'Frontend formatting failed' }
    & npm.cmd run build
    if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed' }
} finally { Pop-Location }
