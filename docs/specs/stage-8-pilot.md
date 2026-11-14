# Stage 8a — Installer pilot (embedded PostgreSQL, no admin rights)

*Fable spec, 2026-11-14. Branch `feature/installer-pilot`, one PR. Goal: prove the riskiest part
works end-to-end on this machine; polish (icons, upgrade path, backups) comes in stage 8b.*

## 0. Decisions (Fable)
- A. **Two run modes.** Dev mode (unchanged): `.env` with `DATABASE_URL`. Bundled mode: when
  `sys.frozen` (PyInstaller) **or** env `JOURNAL_EMBEDDED=1`, and no `DATABASE_URL` is set, the app
  starts its own PostgreSQL. Tests and dev never start an embedded server unless asked.
- B. **Where things live.**
  - Binaries: `{app}\pgsql\` (only `bin`, `lib`, `share` of PostgreSQL 17 — no pgAdmin, docs,
    include, StackBuilder, symbols). Copied from `C:\Program Files\PostgreSQL\17` by the build script.
  - Data: `%LOCALAPPDATA%\teacher-journal\pgdata` (override: env `JOURNAL_DATA_DIR` — used by the
    pilot test so the real profile is not touched). Logs stay in `%LOCALAPPDATA%\teacher-journal\logs`.
  - **Non-ASCII paths are a known PostgreSQL risk** (this machine's profile is `C:\Users\Адмін`, the
    teacher's may be Cyrillic too). Any path handed to `initdb`/`pg_ctl` that is non-ASCII is first
    converted with `GetShortPathNameW` (8.3 name). If that still is non-ASCII (8.3 disabled) →
    fallback data dir `C:\ProgramData\teacher-journal\<sha1(username)[:12]>\pgdata` (users may create
    folders in ProgramData). The pilot must prove which branch works here and record it.
- C. **Server.** `initdb -U journal -E UTF8 --locale=C --auth=scram-sha-256 --pwfile=<tmp>` on first
  run. Superuser `journal`; DB `journal` created after init. Random 32-char password from `secrets`,
  stored in `<data root>\db.secret` (not in logs, not on the command line — pwfile is a temp file
  deleted right after `initdb`). Sorting is done in Python (`ua_sort.py`), so `C` locale is fine.
- D. **Start/stop.** Always through `pg_ctl` (it drops admin rights via a restricted token, so it also
  works under an admin account): `pg_ctl start -w -t 30 -D <data> -l <logs>\postgres.log
  -o "-p <port> -c listen_addresses=127.0.0.1"`. Port: 54329; if busy and not ours → next free in
  54329–54339; chosen port saved in `<data root>\port`. If our server is already running
  (`pg_ctl status`), reuse it. On app exit: `pg_ctl stop -m fast`. No Windows service, no registry.
  Child processes run with `CREATE_NO_WINDOW` (no console flashes).
- E. **Schema.** On every bundled start: `alembic upgrade head` programmatically (bundled
  `alembic.ini` + `migrations/`). Before upgrading a DB that is not at head and not empty →
  stage 8b adds the backup; for the pilot just log it.
- F. **Architecture.** New module `journal/embedded_db.py` (no UI imports): `ensure_running() -> url`,
  `stop()`. `config.database_url()` / `app.py` call it in bundled mode; UI still only touches
  `session_scope()`. Errors → clear Ukrainian message box in `app.py` + full detail in the log.
- G. **Packaging.** PyInstaller **onedir** (`packaging/journal.spec`), windowed, name `TeacherJournal`.
  Exclude unused Qt modules (WebEngine, Pdf, Multimedia, 3D, QML/Quick, etc.) to keep size down.
  Build script `packaging/build.ps1` (ASCII, no admin): PyInstaller → copy trimmed `pgsql` → (if
  `ISCC.exe` found) Inno Setup. Build output in `build/`, `dist/` (git-ignored).
- H. **Installer (Inno Setup 6).** `packaging/installer.iss`: `PrivilegesRequired=lowest`,
  `DefaultDirName={localappdata}\Programs\TeacherJournal`, Start-menu + optional desktop shortcut,
  Ukrainian UI texts. Uninstall removes program files only — **never the data folder** (stated in the
  uninstaller message).
- I. **Smoke mode.** `TeacherJournal.exe --smoke`: start embedded DB, migrate, run
  `AuthService.has_any_teacher()`, print `SMOKE OK <alembic revision>`, stop server, exit 0 (no
  windows; run with `QT_QPA_PLATFORM=offscreen`). Used for the pilot and later CI.

## 1. Acceptance (all on this machine, nothing on the author's screen)
1. `packaging/build.ps1` builds `dist\TeacherJournal\` without admin rights.
2. `--smoke` passes twice with `JOURNAL_DATA_DIR` = a fresh scratch dir **with Cyrillic in the path**
   (first run = initdb + migrate, second = reuse), and once with an ASCII path. Server is stopped after.
3. If Inno Setup is available: silent per-user install (`/VERYSILENT /CURRENTUSER`) to a scratch dir,
   `--smoke` from the installed copy, silent uninstall; data dir survives uninstall.
4. Unit tests for `embedded_db` path/port/secret logic (no real server needed); full `pytest` green;
   dev mode unchanged.
5. Report: dist size, installer size, cold-start time, which path branch (B) was used, problems.

## 2. Out of scope (stage 8b)
Backups before migration, upgrade over an existing install, icon/branding, code signing, a second
Windows account test, moving the data folder.
