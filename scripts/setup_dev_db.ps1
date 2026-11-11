#Requires -RunAsAdministrator
<#
Local dev database setup. Safe to run more than once.

Creates (or updates) role journal_user and databases:
  journal       - the app database
  journal_test  - separate database for pytest (tests never touch app data)
and writes DATABASE_URL + TEST_DATABASE_URL to .env in the project root.

Normal mode: asks for the existing postgres superuser password.
-ResetSuperuserPassword: use only if the postgres password is unknown. It briefly
  allows passwordless login for user postgres from 127.0.0.1 only, sets a new
  password, then restores pg_hba.conf and restarts the PostgreSQL service.

Passwords are sent to psql via stdin (never as command-line arguments).
#>
param([switch]$ResetSuperuserPassword)

$ErrorActionPreference = 'Stop'

$pg   = 'C:\Program Files\PostgreSQL\17'
$hba  = "$pg\data\pg_hba.conf"
$bak  = "$hba.setup-backup"
$svc  = 'postgresql-x64-17'
$psql = "$pg\bin\psql.exe"
$envFile = Join-Path (Split-Path $PSScriptRoot -Parent) '.env'

function Read-Secret([string]$prompt, [switch]$Validate) {
    $secure = Read-Host $prompt -AsSecureString
    $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try { $plain = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr) }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr) }
    if ($Validate -and $plain -notmatch '^[A-Za-z0-9]{8,}$') {
        throw 'Password: latin letters and digits only, at least 8 characters.'
    }
    return $plain
}

function Invoke-Sql([string]$sql) {
    # SQL goes through stdin, so passwords never appear in the process list.
    # -w: never prompt for a password; -X: ignore any user psqlrc.
    $sql | & $psql -U postgres -h 127.0.0.1 -d postgres -w -X -v ON_ERROR_STOP=1 -q -f -
    if ($LASTEXITCODE -ne 0) { throw "psql failed with exit code $LASTEXITCODE" }
}

if ($ResetSuperuserPassword) {
    if (Test-Path $bak) {
        throw "Found $bak from an interrupted run. Restore it over pg_hba.conf manually, restart the '$svc' service, then run again."
    }
    # Read both passwords BEFORE touching pg_hba.conf, so a typo can't leave a half-done setup.
    $newAdminPw = Read-Secret 'New password for superuser postgres' -Validate
    $appPw = Read-Secret 'Password for app user journal_user (new or existing)' -Validate
    Copy-Item $hba $bak
    try {
        # One extra rule at the top: only user postgres, only from 127.0.0.1.
        $original = Get-Content $bak
        Set-Content $hba (@('host all postgres 127.0.0.1/32 trust') + $original) -Encoding ascii
        Restart-Service $svc
        Start-Sleep 3
        Invoke-Sql "ALTER USER postgres PASSWORD '$newAdminPw';"
    }
    finally {
        Copy-Item $bak $hba -Force
        Restart-Service $svc
        Remove-Item $bak
    }
    $adminPw = $newAdminPw
}
else {
    $adminPw = Read-Secret 'Password of PostgreSQL superuser postgres'
    $appPw = Read-Secret 'Password for app user journal_user (new or existing)' -Validate
}

$env:PGPASSWORD = $adminPw
try {
    Invoke-Sql @"
DO `$`$BEGIN
  IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'journal_user') THEN
    ALTER ROLE journal_user WITH LOGIN PASSWORD '$appPw';
  ELSE
    CREATE ROLE journal_user LOGIN PASSWORD '$appPw';
  END IF;
END`$`$;
SELECT 'CREATE DATABASE journal OWNER journal_user ENCODING ''UTF8'''
  WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'journal')\gexec
SELECT 'CREATE DATABASE journal_test OWNER journal_user ENCODING ''UTF8'''
  WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'journal_test')\gexec
"@
}
finally {
    Remove-Item Env:\PGPASSWORD -ErrorAction SilentlyContinue
}

Set-Content $envFile @(
    "DATABASE_URL=postgresql+psycopg://journal_user:$appPw@localhost:5432/journal",
    "TEST_DATABASE_URL=postgresql+psycopg://journal_user:$appPw@localhost:5432/journal_test"
) -Encoding ascii
Write-Host "Done: role journal_user, databases journal and journal_test are ready; .env written to $envFile"
