# Stage 5.1 — Lesson log panel + confirmed journal deletion

*Teacher's feedback after the stage-5 demo (overrides stage-5 decisions). Panel spec by the Fable reviewer; journal deletion decided by the author.*

No migration. `GridData.lessons` already carries date/type/topic.

## A. Lesson log panel (teacher's request)
- **Numbering:** per semester, 1-based, in grid order `(lesson_date, id)` → № = column index + 1. Computed in the UI, never stored.
- **Column header:** painting unchanged (56 px too narrow). Tooltip becomes `Урок № N · dd.MM.yyyy · <type>\n<topic>`.
- **Layout:** in `content_stack` page 0, a horizontal `QSplitter`: grid (stretch 1) + `LessonPanel` (initial 340 px, min 260, children not collapsible). Checkable toolbar button «Теми уроків», checked by default, hides/shows the panel (state per session). Empty-state page unchanged.
- **Panel** (`ui/lesson_panel.py`): title «Проведені уроки», read-only `QTableWidget`, single-row selection, `NoFocus` (keyboard entry stays in the grid).
  - Columns: `№` (36), `Дата` (56, `dd.MM`), `Тема` (stretch, word-wrapped, `resizeRowsToContents`, never elided; tooltip = full text).
  - Regular lesson: topic, or muted italic «тема не вказана». Other types: `<Type name>: <topic>` or just `<Type name>`; row background = existing `lesson_*_soft` token.
  - API: `set_lessons(lessons, read_only)`, `select_lesson(lesson_id)`; signals `lesson_selected(int)`, `lesson_edit_requested(int)`, `lesson_delete_requested(int)`.
- **Interactions:** row click → select that column in the grid (keep current row, else 0) and return focus to the grid; row double-click → `LessonDialog(..., focus_topic=True)` (topic field focused, text selected); context menu «Редагувати урок» / «Видалити урок»; no inline editing; grid current-column change highlights + scrolls the panel row, without signal loops.
- **Read-only** (archived class): panel visible, selection works, no edit/delete.
- **Sync:** `reload_grid()` is the only feed (`panel.set_lessons`) — covers Ctrl+N, create, edit, delete, semester switch; highlight follows the selected lesson.

## B. Journal deletion with contents (author's decision)
- Contract: `delete_journal(teacher_id, journal_id, with_contents: bool = False)`. Already implemented in `JournalService` (deletes final grades, lessons with their marks, then the journal, in one transaction; without the flag it still refuses with «У журналі є уроки чи оцінки — його не можна видалити»).
- UI («Ще» → «Видалити журнал»): empty journal (`lesson_count == 0` from a fresh `list_journals`/grid state) → ordinary confirm; otherwise a typed-confirmation dialog like `DeleteLessonDialog`: «Журнал «9-А · Математика» містить уроків: N. Разом з ним буде безповоротно видалено всі уроки, відмітки та оцінки. Щоб підтвердити, введіть «видалити».» → call with `with_contents=True`, then back to the list. Use the live lesson count (both semesters) — not a stale value.
- Fake service: support `with_contents` with the same refusal message.

## C. Folded-in review notes (PR #9)
1. `refresh()`: if `reload_grid()` fails → `show_list()`.
2. `reload_grid()` without `select_lesson_id` restores the current cell by `(student_id, lesson_id)`, fallback `(0, 0)`.
3. `_on_edit_lesson` and `_on_delete_lesson` call `grid_view.flush_pending()` first.

## Files
- Agent: `ui/lesson_panel.py` (new), `ui/journals_page.py`, `ui/journal_grid.py` (tooltip only), `ui/journal_dialogs.py` (`focus_topic`, journal delete dialog), `tests/fakes/*`, `tests/ui/*`.
- Orchestrator: `services/*`, `repositories/*`, `theme.py`, `main_window.py`. No new tokens; colours only via `theme.color()` read at paint/populate time; `refresh_icons()` must repopulate the panel. Optional QSS hooks: `#LessonPanel`, `#LessonPanelTitle` (list them in the report).

## Tests (pytest-qt, offscreen, fake)
Rows/numbers 1..n incl. same-date order by id; text for all four types with/without topic + placeholder; header tooltip contains `№ N`; row click moves grid column keeping row; grid navigation moves panel highlight; double-click opens dialog with `focus_topic`, edited topic appears after reload; Ctrl+N adds+highlights a row; delete removes it; semester switch replaces rows; archived class → no edit/delete signals; toggle hides/shows; `refresh()` with `fail_next` falls back to list; `refresh()` keeps current cell; pending «1» committed (one `set_cell`) before delete dialog and typed confirmation required; journal delete: empty → simple confirm, with lessons → typed dialog with correct count → `with_contents=True`, cancel → nothing deleted.

## Done
Full `pytest` green; no colour literals; light and dark offscreen screenshots; Fable `APPROVE`.
