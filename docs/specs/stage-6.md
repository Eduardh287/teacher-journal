# Stage 6 — Teacher feedback 2: thematic/semester/annual grades, homework, numbering

*Fable spec (base + amendment «Зошит»), 2026-11-13, with the author's answers to the open questions. Branch `feature/stage-6-grades`, one PR, after `fix/qa-findings` merges. Excel export moves to a later stage.*

## 0. Binding decisions (teacher via author)
- A. Lesson numbering in the panel is continuous for the school year (1 Sep → end of semester II); only real dated lessons are numbered.
- B. «Домашнє завдання»: field in the lesson dialog AND inline edit in the panel (column «Д/з»).
- C. Panel formats: date dd.MM; «тема не вказана»; «Контрольна робота: тема» (by analogy «Тест: тема», «Проєкт: тема»).
- D. Subjects: keep all, add «ПП ТФВ» (migration, ON CONFLICT DO NOTHING).
- E. A lesson with ANY entry (grade, н/хв/з, comment) cannot be deleted — explain why; empty lesson → ordinary confirm. Journal deletion with typed word unchanged.
- F. Last grade is 12: 11 → 12 promoted, 12 → archive.
- G. Rollover catch-up in ONE launch to the current school year; **create empty archived classes for the skipped years** (author's answer).
- H. Dated lesson types added: «Тест» (`quiz`, abbr. «Т») and «Проєкт» (`project`, abbr. «Пр»).
- I. Dateless column kinds: exactly «Тематична» (abbr. «Тем»), «Зошит» (abbr. «Зош»), «Семестрова», «Річна». No date can be set for them.
- J. Thematic = arithmetic mean of ALL lesson grades (every dated type, equal weight; «Зошит» excluded) since the previous thematic column (or semester start). Half up (7.5 → 8). Computed automatically; teacher can override manually.
- K. Semester = mean of the thematic values of that semester; annual = mean of the two semester values. Auto, half up, overridable. Columns at the END of the table: sem I tab → «Семестрова»; sem II tab → «Семестрова», «Річна».
- L. «н/а» (не атестований) — a DISPLAY marker only; **in every calculation н/а = 0** (author, 13.11.2026):
  - a student's thematic with no grades in its period → shows «н/а» and counts as 0 in the semester mean (e.g. thematics н/а, 8, 10 → semester = (0+8+10)/3 = 6);
  - semester with NO thematic columns → «н/а» (= 0 in the annual);
  - annual = half-up of (sem1 + sem2) / 2 with н/а or missing = 0 (8 and н/а → 4; 9 and н/а → 5); if both are н/а → «н/а».
  - A computed value of 0 after averaging (all inputs н/а) is shown as «н/а».
- M. «Зошит» grade is recorded only; it counts in NO average; grade only (no н/comment). A «Зошит» column with grades cannot be deleted until cleared; empty → ordinary confirm. Thematic and «Зошит» need no caption; no thematic column between two lessons of the same day (defaults, listed for the teacher).

## 1. Data model — ONE migration (on top of `c12d062be128`)
- `lessons.homework TEXT NULL` (`MAX_HOMEWORK = 500`).
- Recreate `ck_lessons_lesson_type` with `quiz`, `project` (`test` stays «Контрольна робота»). Downgrade sets them to `regular` first.
- `extra_columns`: `id`, `journal_id` (FK RESTRICT), `kind` CHECK IN (`thematic`,`notebook`), `semester` CHECK 1/2, `after_date DATE NOT NULL` (hidden sort key copied from the anchor lesson), `created_at`; `UNIQUE(journal_id, kind, after_date)`. Model `ExtraColumn`, enum `ExtraColumnKind`.
- `extra_grades`: PK (`column_id` FK CASCADE, `student_id` FK RESTRICT, indexed), `grade` CHECK 1–12. Thematic → manual override; notebook → the grade itself.
- `final_grades` reused; a row = manual override of semester_1 / semester_2 / annual.
- Manual «н/а» override: allowed for thematic/semester/annual (teacher may set н/а by hand) — store as a nullable `grade` + `is_na BOOLEAN` on `extra_grades` and `final_grades` (CHECK: exactly one of grade / is_na). Key «н» on a computed cell sets н/а; digits set a grade; Del clears the override.
- `INSERT ... 'ПП ТФВ' ON CONFLICT (name) DO NOTHING`; downgrade deletes it only if unused.
- Ordering at equal `after_date`: lessons → «Зошит» → «Тематична». A column sits after every lesson with `lesson_date <= after_date`. `apply_boundaries`, `delete_journal_contents`, «journal has contents», `student_has_records` cover extra columns/grades.
- Computed values are never stored; recomputed on read by pure `services/grade_calc.py` (integer half-up: `(2*sum + n) // (2*n)`).

## 2. Computation details
- Counted: `lesson_entries.grade IS NOT NULL` (late + grade counts; н/хв/з or comment without grade ignored). «Зошит» lives in `extra_grades` → excluded by construction; it is not a period boundary.
- Thematic Tk period: lessons of the same journal and semester with `prev.after_date < lesson_date <= Tk.after_date`. Grades after the last thematic column affect nothing until a column is added.
- Effective value = override (grade or н/а) if present, else auto (grade or н/а).
- Semester: no thematic columns in the semester → н/а; else half-up mean over ALL thematic columns of the semester, each effective value with н/а = 0; result 0 → н/а.
- Annual: half-up of (s1 + s2)/2 with missing/н/а = 0; both missing/н/а → н/а.
- Withdrawn students: computed & shown; row read-only; listed if they have entries or extra/final grades.

## 3. Contract (`journal_types.py`, orchestrator first)
- `LessonTypeCode` + `"quiz"`, `"project"`; `LessonInfo` + `homework: str | None = None`, `number: int = 0`.
- `ExtraColumnInfo(id, kind, semester, after_date, ordinal, grade_count)`.
- `GridColumn(kind: "lesson"|"thematic"|"notebook"|"semester"|"annual", id: int | None)`.
- `ComputedKey = tuple[str, int]` — ("thematic", id) | ("notebook", id) | ("semester", 1|2) | ("annual", 0).
- `ComputedCell(auto: int | None, auto_na: bool, total: int, count: int, override: int | None, override_na: bool)` with `.value` / `.is_na`.
- `GridData` + `columns`, `extra_columns`, `computed: dict[tuple[int, ComputedKey], ComputedCell]`.
- Methods: `create_lesson(..., homework=None)`, `update_lesson(..., homework)`, `set_homework(teacher_id, lesson_id, homework) -> LessonInfo`; `delete_lesson` rule E («Урок має оцінки чи позначки (N) — його не можна видалити. Спершу очистьте клітинки цього уроку.»); `create_column(teacher_id, journal_id, kind, after_lesson_id)`, `move_column(...)`, `delete_column(...)` («Після цього уроку вже є такий стовпчик»; notebook with grades → «У стовпчику «Зошит» є оцінки (N) — його не можна видалити. Спершу очистьте їх.»); `set_override(teacher_id, journal_id, student_id, key, grade: int | None, na: bool = False) -> dict[ComputedKey, ComputedCell]`; `student_computed(teacher_id, journal_id, student_id)`.
- Rollover: `LAST_GRADE = 12`; jump to the current year; empty archived classes for skipped years; `RolloverItem.years_skipped`; dialog line «9-А (2024-2025) → 11-А (2026-2027) · пропущено 1 рік».

## 4. UI
- Grid: thematic «Тем» + ordinal (`col_thematic_soft`), «Зош» + ordinal (`col_notebook_soft`), finals «Сем.» / «Річна» at the end (`col_final_soft`, bold separator). Lesson abbreviations «Т», «Пр» (`lesson_quiz_soft`, `lesson_project_soft`). Computed cells: digits (chain rule) → override; «н» → н/а override; Del → clear; х/з/F2 ignored. Auto = regular weight; manual = bold + accent underline; «н/а» shown as text. Tooltips: «Середнє 7,50 (6 оцінок) → 8» / «Виставлено вручну…» / «н/а — немає оцінок за тему» / annual explains 0 for н/а. Notebook cells: digits/Del; tooltip «Оцінка за зошит — не враховується в середніх».
- «Додати стовпчик» menu button: «Тематична» (Ctrl+T), «Зошит» (Ctrl+Shift+T) — after the last lesson of the open semester, no dialog. Header menu for both: «Перемістити…», «Видалити». Lesson delete with entries → information dialog with the service text.
- Lesson panel: №, Дата, Тема, Д/з; № from `LessonInfo.number`; separator rows «Тематична»/«Зошит»; Д/з inline QLineEdit (Enter saves, Esc cancels) → `homework_edited(lesson_id, text)`; signals `column_move_requested`, `column_delete_requested`; `set_items(lessons, extra_columns, read_only)`.
- Lesson dialog: six dated types + «Домашнє завдання».
- Theme tokens (orchestrator, verify contrast ≥ 4.5 with `text`): light `lesson_quiz_soft #CFF9FE`, `lesson_project_soft #FCE7F6`, `col_thematic_soft #E0EAFF`, `col_notebook_soft #FEF7C3`, `col_final_soft #EAECF0`; dark `#0E3A44`, `#3F1D38`, `#1F2A52`, `#3A3210`, `#2A2F3A`.

## 5. Work split
| Owner | Files |
|---|---|
| Orchestrator (first) | `services/journal_types.py`, `ui/theme.py`, `models/__init__.py`, `LESSON_TYPES` in `ui/journal_dialogs.py`, `tests/fakes/*`; later `scripts/qa/screens.py`, `tests/e2e/*`, docs |
| A — Sonnet (sole owner of models/migrations/services) | migration, `models/enums.py`, `models/journal.py`, `repositories/*`, `services/grade_calc.py`, `journal_service.py`, `settings_service.py`, `rollover_service.py`, root tests |
| B — Sonnet | `ui/journal_grid.py`, `ui/journals_page.py`, `tests/ui/test_journal_grid.py`, `tests/ui/test_journals_page_columns.py` |
| C — Sonnet | `ui/lesson_panel.py`, `ui/journal_dialogs.py` (after orchestrator commit), `ui/rollover_dialog.py`, `tests/ui/test_lesson_panel.py`, `test_rollover_dialog.py`, `test_lesson_dialog.py` |

## 6. Tests and done criteria
See the Fable spec items: grade_calc half-up and boundaries, н/а rules (no thematic → н/а; empty period → н/а excluded from semester; annual with н/а as 0), overrides incl. н/а, notebook excluded and not a boundary, quiz/project counted, numbering continuous and unaffected by dateless columns, homework, rule E, column create/move/delete rules, boundary change and journal delete with extra columns, 11→12, 12→archive, multi-year catch-up with archived skipped years, upgrade/downgrade, «ПП ТФВ» idempotent; UI keys/tooltips/menus/panel/dialog/rollover line. Full pytest green; no colour literals; offscreen screenshots (two thematic + Зошит + override; sem II with finals; panel with Д/з editor; dialog with six types; delete refusal; rollover catch-up; «Додати стовпчик» menu); Fable APPROVE.
