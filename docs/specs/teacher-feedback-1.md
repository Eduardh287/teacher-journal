# Teacher feedback 1 (practical test, 2026-11-17)

*Fable spec. Branch `feature/teacher-feedback-1`, one PR. The teacher's edits have priority over
earlier Fable decisions. Author's answers (17.11.2026) are quoted where they decide something.*

## A. Paste a whole list of students
Finding: bulk import already exists («Додати списком» on the class page, `ImportStudentsDialog`,
strips leading numbers, tabs from Excel columns become spaces). The teacher most likely pasted into
the single-student field «Додати учня» (a `QLineEdit`, which keeps only one line).
Sources (author): Word/plain text and Excel.
1. In `StudentDialog` (add mode), pasting text that has **2+ non-empty lines** into the name field
   opens `ImportStudentsDialog` pre-filled with that text (instead of squashing it into one name).
   If the import dialog is accepted, the student dialog closes as "changed"; if cancelled, the
   student dialog stays open with an empty field. Rename mode: unchanged (one name only).
2. `ImportStudentsDialog` gets an optional `initial_text` argument; preview runs immediately.
3. Excel rows like `1<TAB>Іваненко<TAB>Олена<TAB>Петрівна` and `Іваненко<TAB>Олена` must become
   «Іваненко Олена Петрівна» / «Іваненко Олена» (already true — cover with tests). Windows `\r\n` too.
4. Hint under «Додати учня» field: «Можна вставити одразу весь список — кожен учень з нового рядка.»

## B. Row colour per student
Author: just a marker, no label; **not** exported to Excel.
1. Migration: `students.row_color VARCHAR(20) NULL` (NULL = no colour) + CHECK that it is NULL or
   one of the keys of `theme.ROW_COLORS` (yellow, green, blue, pink, purple, orange). The service
   validates the key too (services must not import `ui`: keep the key tuple in the service
   and a test that it equals `theme.ROW_COLORS` keys).
2. Service: `ClassService.set_student_color(teacher_id, student_id, color: str | None)`;
   `StudentInfo` gets `row_color`. The journal grid data (`get_grid` students) carries `row_color`
   too — no extra queries (query-count tests must stay as they are).
3. Where to set: class page student row — a «Колір» button/menu next to «Змінити»/«Прибрати»
   with the six colours (swatch icon + name) and «Без кольору». Also right-click on the student
   name in the journal grid → same menu. Change is visible immediately.
4. Painting (both themes, colours only via `theme.color(token)`): the whole row of that student
   gets the soft background (№ + name + every grade cell). A cell's own tint (absent/sick/late
   marks, lesson-type tint, thematic/semester columns) wins over the row colour; selection and
   focus look unchanged. Withdrawn students keep their muted text.
5. Colour is per student (follows the student into every journal of the class).

## C. Periodic backup reminder
Author: the app reminds and offers; the teacher chooses the period; file names = date and time
of saving (current names `journal_YYYY-MM-DD_HH-MM-SS_manual.dump` already carry them; the dialog
shows the name it will use).
1. Backups settings card: «Нагадувати про резервну копію»: «Не нагадувати» / «Щодня» /
   «Щотижня» (default) / «Щомісяця» (30 days). Stored via `theme.app_settings()`
   (`backup_reminder_days`: 0/1/7/30). The last reminder copy time: `backup_reminder_last` (ISO).
2. After login (and once an hour while open), if the period has passed since the last copy made
   from the reminder **or** manually from settings (any `manual` copy counts; automatic exit copies
   do not — they stay on the same computer), show: «Минуло N днів від останньої резервної копії.
   Зробити копію зараз?» Buttons: «Зробити копію…» (folder picker, starting at the last folder
   used for reminder copies, else the backups folder; e.g. a USB stick) / «Пізніше» (ask again
   next day). First run ever (no copy yet) → remind after one period from first login, not at once.
3. Copy = `BackupService.create_backup("manual")` into the chosen folder, via the existing busy
   dialog; success shows the full file name and «Відкрити папку»; failure shows a clear message.
4. Glue (orchestrator): the hook in `MainWindow`/`app.py`.

## Acceptance
- Unit + offscreen UI tests for A1–A4, B1–B4, C1–C3 (light + dark where painting is involved).
- Full `pytest` green; app starts; migration up/down tested on journal_test.
- `docs/assumptions.md`: section «Правки викладачки 1» with the choices above.
