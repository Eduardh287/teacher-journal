# Excel export (roadmap item 3)

*Fable spec, 2026-11-15. Branch `feature/excel-export`, one PR. Author's answers (15.11.2026):
the teacher copies grades by hand into the **school electronic journal**; the file holds the
**grade table as in the app**; the period is **any date range**.*

## 0. Decisions
- A. **What.** One journal (class + subject) → one `.xlsx` file, one sheet. Content = the grade table
  exactly as the app shows it: students in the app's order (Ukrainian alphabet), dated lesson
  columns, «Тематична», «Зошит», «Семестрова», «Річна», with the app's cell texts
  (`10`, `н`, `хв`, `з`, `з 9`, `н/а`, computed thematic/semester/annual values incl. manual overrides).
  Withdrawn («вибув») students are included only if they have at least one entry in the range,
  marked «(вибув)».
- B. **Period.** Dialog with «з» / «по» dates and presets: «Поточний семестр» (default),
  «I семестр», «II семестр», «Весь рік», «Цей місяць». Included columns:
  - dated lessons with `from ≤ date ≤ to`;
  - «Тематична» / «Зошит»: when their anchor lesson is in the range;
  - «Семестрова» of a semester: when the range contains that semester's last day;
  - «Річна»: when the range contains the last day of semester II.
  A range spanning both semesters keeps the app's order (sem I columns, then sem II).
  Empty range (no columns) → friendly message, no file.
- C. **Layout (print- and copy-friendly).**
  - Row 1: «<Предмет>, <клас> — <dd.mm.yyyy>–<dd.mm.yyyy>» (bold). Row 2: «Сформовано <date>».
  - Header rows 3–4: row 3 = lesson number/abbreviation as in the app (`1`, `Т`, `Пр`, `Тем`, `Зош`,
    `Сем I`, `Річна`…), row 4 = date `dd.mm` (empty for dateless columns).
  - Column A «№», column B «Учень» (full name). Freeze panes at C5. Narrow equal grade columns.
  - Numbers are written as numbers (so Excel can sum/sort); markers as text; centred.
  - Cell comments from the app become Excel cell comments.
  - Light, fixed print palette (thin borders; soft fill for Тематична/Семестрова/Річна headers);
    this is a document, not UI, so `theme.py` tokens do not apply here.
  - Page setup: landscape, fit to 1 page wide, header rows repeated when printed.
  - Second sheet «Уроки»: №, дата, тип, тема, д/з for the dated lessons in the range
    (useful when filling the school journal's lesson topics).
- D. **Where.** Button «Експорт в Excel…» in the journal view (next to the other journal actions).
  Save dialog, default folder = Documents (remembered via `theme.app_settings()` key `export_dir`),
  default name `<клас>_<предмет>_<yyyy-mm-dd>_<yyyy-mm-dd>.xlsx` with unsafe characters replaced.
  After saving: «Файл збережено» + «Відкрити папку». Writing fails (file open in Excel, no
  permission) → clear Ukrainian message, nothing half-written (write to temp, then replace).
- E. **Architecture.** `services/export_service.py`: builds a pure data model
  (`ExportTable`: title, columns with header texts, rows with cell texts/numbers/comments, lessons
  list) from `JournalService` data (reuse `get_grid` for each semester; no duplicated grade
  logic). `services/xlsx_writer.py` (openpyxl, no Qt) writes `ExportTable` to a path. UI: a small
  dialog in `ui/` + the button; UI never imports sqlalchemy/models/repositories.
- F. **Privacy.** Exported files contain student data: never written inside the repo
  (`*.xlsx` is git-ignored anyway); tests write only to `tmp_path`.

## 1. Acceptance
1. Unit tests for range → column selection (lesson in/out, anchored Тематична/Зошит, semester and
   annual inclusion rules, cross-semester order, empty range), cell texts identical to the app's
   (reuse the grid model's text function if possible), withdrawn-student rule, file-name sanitising.
2. Writer tests: open the produced file with openpyxl and check title, headers, numbers vs text,
   comments, freeze panes, print setup, «Уроки» sheet; failure leaves no partial file.
3. UI offscreen tests: dialog presets fill the dates, button wiring, success and error messages
   (light + dark).
4. Full `pytest` green; `docs/assumptions.md` gets an «Експорт в Excel» section listing these choices
   as not yet confirmed by the teacher.
