# Stage 7 — Backups (7a), password change and brute-force protection (7b)

*Fable spec, 2026-11-14. Two PRs: `feature/stage-7a-backups`, then `feature/stage-7b-password`.
Decisions below are Fable's (delegated by the author); open points for the teacher go to
`docs/assumptions.md`.*

## 7a. Backups

### 0. Decisions
- A. **Format.** `pg_dump -Fc` of the app database (schema + data). File name
  `journal_<YYYY-MM-DD_HH-MM-SS>_<kind>.dump`, kind ∈ `auto` | `manual` | `before-restore` |
  `before-migration`. `*.dump` is already git-ignored.
- B. **Tools.** `pg_dump` / `pg_restore` from `embedded_db.pgsql_dir()/bin` (bundled: `{app}\pgsql`;
  dev: PostgreSQL 17 install). Connection parameters come from the current engine URL
  (`journal.db.get_engine().url`). **Password only via the `PGPASSWORD` environment variable of the
  child process** — never on the command line, never logged. Children run with `CREATE_NO_WINDOW`.
- C. **Cyrillic paths.** The backup folder may be Cyrillic (`C:\Users\Адмін\...`) or a USB stick.
  Never pass the backup file path to `pg_dump`/`pg_restore`: dump goes to the child's **stdout**
  and Python writes the file (to `<name>.part`, then atomic rename); restore feeds the file through
  **stdin**. This also avoids partial files on failure.
- D. **Where.** Default folder `<data root>\backups`, where data root = `JOURNAL_DATA_DIR` or
  `%LOCALAPPDATA%\teacher-journal` (same rule as logs). The teacher may choose another folder
  (e.g. a USB stick or a synced cloud folder) — stored in `QSettings` key `backup_dir`. If the chosen
  folder is unavailable, the copy goes to the default folder and the UI says so.
- E. **Automatic copy on exit.** When the main window closes after a successful login, an `auto`
  copy is made before the embedded server stops (hook in `MainWindow.closeEvent`, not `atexit`).
  Small modal "Створюю резервну копію…" without a cancel button; on failure — a warning, then the
  app still exits (never trap the teacher). Keep the **10 newest `auto`** copies in the folder the
  copy was written to; `manual`, `before-restore`, `before-migration` are never deleted automatically.
- F. **Before migration (bundled mode).** In `embedded_db.ensure_running()`, if the DB has an
  `alembic_version` that differs from the script head, make a `before-migration` copy into the
  default folder before `upgrade head`. If the copy fails → do not migrate, raise `EmbeddedDbError`
  with a clear Ukrainian message.
- G. **Restore** (Settings → «Резервні копії» → «Відновити з копії…», file dialog opens in the backup
  folder):
  1. Validate: `pg_restore --list` succeeds; read the backup's revision with
     `pg_restore --data-only --table=alembic_version` (stdout, parse the COPY row). Unknown/newer
     revision than the app knows → refuse («Копію створено новішою версією програми»).
  2. Confirmation dialog showing the copy's date and kind; the teacher types «відновити»
     (same pattern as journal deletion). Warn: all current data will be replaced; after restore,
     sign in with the password that was valid at the time of the copy.
  3. Make a `before-restore` copy of the current state (abort restore if this fails).
  4. Dispose the engine; `DROP SCHEMA public CASCADE; CREATE SCHEMA public;` then
     `pg_restore --no-owner --no-privileges --single-transaction --exit-on-error` from stdin; then
     `alembic upgrade head` (older copies get migrated).
  5. If step 4 fails → automatically restore the `before-restore` copy the same way and tell the
     teacher nothing was changed. Full details only in the log.
  6. Success → message «Дані відновлено. Програма закриється — відкрийте її знову.» and quit
     (no `auto` copy on this exit).
- H. **UI** — new card «Резервні копії» on the Settings page (`ui/settings_cards.py`, colours only via
  theme tokens): current folder (elided path), date/time of the newest copy or «Копій ще немає»,
  buttons «Створити копію зараз», «Відкрити папку», «Змінити папку…», «Відновити з копії…».
  Long operations show a busy modal; UI stays offscreen-testable.
- I. **Architecture.** `services/backup_service.py` (no Qt): `create_backup(kind) -> Path`,
  `list_backups()`, `rotate()`, `inspect(path) -> BackupInfo`, `restore(path)`. Subprocess calls go
  through one small runner that tests can fake. UI calls the service; no `sqlalchemy` imports in UI.
  Folder preference (QSettings) is read in UI and passed to the service.

### 1. Acceptance
1. Unit tests (fake runner): file naming, `.part` → rename, rotation keeps 10 newest `auto` only,
   unavailable custom folder → default + flag, revision parsing, newer revision refused, restore
   failure triggers rollback-restore, password never in argv or log records.
2. Integration tests against `journal_test` **only** (skip if `pg_dump` not found): dump → modify →
   restore → data equals original; backup folder path with Cyrillic characters.
   Tests must never touch the `journal` database or the real `%LOCALAPPDATA%`.
3. UI test (offscreen, pytest-qt): card renders in light and dark themes; buttons call the service.
4. Full `pytest` green; dev mode unchanged; `--smoke` still passes for the bundled build is not
   required in this PR (no installer rebuild).

## 7b. Password change and brute-force protection (spec detail before its PR)
- «Змінити пароль» card in Settings: current password + new + repeat; same length rule as
  registration; Argon2 re-hash.
- Throttling: after 5 consecutive failed logins for a username, lock for 30 s, doubling per further
  failure up to 15 min; counters and `locked_until` stored in `teachers` (Alembic migration; backup
  of the working DB before migrating). Unknown usernames are throttled in memory the same way so
  the response does not reveal whether the login exists.
- Forgotten password (author's decision 14.11.2026: **both**):
  1. Recovery code — shown once after registration and after each password change (copy button,
     "write it down" hint); stored only as an Argon2 hash; «Забули пароль?» on the login dialog
     asks for login + code + new password; using the code issues a new one. Same throttling applies.
  2. Fallback when the code is lost too — an author-only script `scripts/reset_password.py`
     (run locally on the teacher's computer, asks for the new password via `getpass`, works in
     dev and bundled mode), documented in README.
