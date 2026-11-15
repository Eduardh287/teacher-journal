# Build TeacherJournal: PyInstaller -> trimmed PostgreSQL -> (optional) Inno Setup installer.
# ASCII only, no admin rights needed. Run from anywhere: powershell -File packaging\build.ps1
param(
    [string]$PgSource = "C:\Program Files\PostgreSQL\17",
    [switch]$SkipInstaller
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { $python = "python" }

# Single version source: pyproject.toml (passed to the installer below).
$version = (Select-String -Path (Join-Path $root "pyproject.toml") -Pattern '^version\s*=\s*"([^"]+)"').Matches[0].Groups[1].Value
if (-not $version) { throw "version not found in pyproject.toml" }
"Version: $version"

# PyInstaller may be installed only for the system Python: make it importable from the venv.
$ErrorActionPreference = "Continue"
& $python -c "import PyInstaller" 2>$null
$haveIt = ($LASTEXITCODE -eq 0)
$ErrorActionPreference = "Stop"
if (-not $haveIt) {
    $sysPython = Get-Command python -ErrorAction SilentlyContinue
    if (-not $sysPython) { throw "PyInstaller is not installed for the venv and no system Python was found" }
    $env:PYTHONPATH = Join-Path (Split-Path -Parent $sysPython.Source) "Lib\site-packages"
}

Remove-Item -Recurse -Force (Join-Path $root "build"), (Join-Path $root "dist") -ErrorAction SilentlyContinue
& $python -m PyInstaller --noconfirm --clean --distpath dist --workpath build packaging\journal.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

# Trimmed PostgreSQL: only bin, lib, share.
$dest = Join-Path $root "dist\TeacherJournal\pgsql"
New-Item -ItemType Directory -Force $dest | Out-Null
foreach ($d in "bin", "lib", "share") {
    Copy-Item -Recurse -Force (Join-Path $PgSource $d) (Join-Path $dest $d)
}
# Drop client tools and pgAdmin-related leftovers the app never uses.
$keepBin = "initdb.exe","pg_ctl.exe","postgres.exe","pg_dump.exe","pg_restore.exe","psql.exe","pg_isready.exe"
Get-ChildItem (Join-Path $dest "bin") -File | Where-Object {
    $_.Extension -eq ".exe" -and ($keepBin -notcontains $_.Name)
} | Remove-Item -Force
Get-ChildItem (Join-Path $dest "share") -Directory -Recurse -Filter "doc" -ErrorAction SilentlyContinue | Remove-Item -Recurse -Force
Remove-Item -Recurse -Force (Join-Path $dest "share\locale") -ErrorAction SilentlyContinue
# PostgreSQL licence travels with the binaries (into dist and so into the installer).
$licence = Join-Path $PgSource "server_license.txt"
if (-not (Test-Path $licence)) { throw "PostgreSQL licence file not found: $licence" }
Copy-Item -Force $licence (Join-Path $dest "LICENSE-PostgreSQL.txt")

$size = (Get-ChildItem (Join-Path $root "dist\TeacherJournal") -Recurse -File | Measure-Object Length -Sum).Sum
"dist\TeacherJournal size: {0:N0} MB" -f ($size / 1MB)

if ($SkipInstaller) { return }
$iscc = @(
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1
if ($iscc) {
    & $iscc "/DAppVersion=$version" (Join-Path $root "packaging\installer.iss")
    if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed" }
} else {
    "Inno Setup not found - installer skipped"
}
