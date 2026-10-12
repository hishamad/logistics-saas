param(
    [string]$SourceDatabase = 'freight',
    [string]$DbHost = '127.0.0.1',
    [int]$Port = 55432,
    [string]$DbUser = 'freight'
)
$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$runtime = Join-Path $repo '.runtime'
New-Item -ItemType Directory -Path $runtime -Force | Out-Null
$suffix = [guid]::NewGuid().ToString('N')
$target = "freight_restore_$suffix"
$dump = Join-Path $runtime "restore-check-$suffix.dump"
$pgArguments = @('-w','-h',$DbHost,'-p',"$Port",'-U',$DbUser)
$created = $false
try {
    & pg_dump.exe @pgArguments -Fc --schema=public -f $dump $SourceDatabase
    if ($LASTEXITCODE -ne 0) { throw 'Backup failed' }
    & createdb.exe @pgArguments -T template0 $target
    if ($LASTEXITCODE -ne 0) { throw 'Could not create isolated restore-check database' }
    $created = $true
    # The target was created above and contains no user data. Replace its empty
    # public schema so the archive can recreate it on PostgreSQL 13 and 17.
    if ($target -notmatch '^freight_restore_[a-f0-9]{32}$') { throw 'Invalid restore target' }
    & pg_restore.exe @pgArguments --clean --if-exists --no-owner --no-acl --exit-on-error -d $target $dump
    if ($LASTEXITCODE -ne 0) { throw 'Restore failed' }
    $rows = & psql.exe @pgArguments -d $target -Atc 'SELECT json_build_object(''workspaces'',(SELECT count(*) FROM workspaces),''revisions'',(SELECT count(*) FROM revisions),''runs'',(SELECT count(*) FROM runs),''revision'',(SELECT version_num FROM alembic_version));'
    if ($LASTEXITCODE -ne 0) { throw 'Restored schema could not be read' }
    $report = @{ verified_at=[datetime]::UtcNow.ToString('o'); source=$SourceDatabase; restored=$target; data=($rows | ConvertFrom-Json); archive=(Split-Path -Leaf $dump); archive_sha256=(Get-FileHash -LiteralPath $dump -Algorithm SHA256).Hash }
    $report | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $repo 'docs/backup-verification.json') -Encoding utf8
    Write-Output $rows
    Write-Output 'Backup restored successfully into an isolated database. Archive remains in .runtime.'
} finally {
    # Drop only the fresh disposable database created by this exact invocation.
    if ($created -and $target -match '^freight_restore_[a-f0-9]{32}$' -and $target -ne $SourceDatabase) {
        & dropdb.exe @pgArguments $target
        if ($LASTEXITCODE -ne 0) { Write-Warning "Could not remove disposable restore database $target" }
    }
}
