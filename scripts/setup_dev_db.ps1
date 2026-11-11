#Requires -RunAsAdministrator
# One-time local dev database setup (run as Administrator).
# - temporarily enables trust login from localhost
# - sets a new password for the postgres superuser
# - creates role journal_user and database journal
# - restores pg_hba.conf
# - writes DATABASE_URL to .env in the project root (one level above this script)
# Passwords are typed by you; they go only to PostgreSQL and the local .env file.
$ErrorActionPreference = 'Stop'

$pg   = 'C:\Program Files\PostgreSQL\17'
$hba  = "$pg\data\pg_hba.conf"
$bak  = "$hba.bak"
$svc  = 'postgresql-x64-17'
$psql = "$pg\bin\psql.exe"
$envFile = Join-Path (Split-Path $PSScriptRoot -Parent) '.env'

function Read-Plain([string]$prompt) {
    $s = Read-Host $prompt -AsSecureString
    $p = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($s))
    if ($p -notmatch '^[A-Za-z0-9]{8,}$') { throw 'Password: latin letters and digits only, at least 8 characters.' }
    return $p
}

$adminPw = Read-Plain 'New password for superuser postgres'
$appPw   = Read-Plain 'Password for app user journal_user'

Copy-Item $hba $bak -Force
try {
    $lines = Get-Content $bak | ForEach-Object {
        if ($_ -notmatch '^\s*#' -and $_ -match '^\s*host') { $_ -replace '(scram-sha-256|md5|password)\s*$', 'trust' } else { $_ }
    }
    Set-Content $hba $lines -Encoding ascii
    Restart-Service $svc
    Start-Sleep 3

    & $psql -U postgres -h 127.0.0.1 -v ON_ERROR_STOP=1 -c "ALTER USER postgres PASSWORD '$adminPw';"
    & $psql -U postgres -h 127.0.0.1 -v ON_ERROR_STOP=1 -c "CREATE ROLE journal_user LOGIN PASSWORD '$appPw';"
    & $psql -U postgres -h 127.0.0.1 -v ON_ERROR_STOP=1 -c "CREATE DATABASE journal OWNER journal_user ENCODING 'UTF8';"
}
finally {
    Copy-Item $bak $hba -Force
    Restart-Service $svc
}

Set-Content $envFile "DATABASE_URL=postgresql+psycopg://journal_user:$appPw@localhost:5432/journal" -Encoding ascii
Write-Host "Done: database 'journal' created, pg_hba.conf restored, .env written to $envFile"
