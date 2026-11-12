# Stage 5 — Журнали, уроки, таблиця оцінок

*Spec written by the Fable reviewer (2026-11-11). Agents implement exactly this; questions go to the orchestrator.*

## 1. Scope
In: journal list/create/delete; lessons (create/edit/delete); per-semester grid with keyboard entry of attendance, grades 1–12, comments; autosave per cell; CASCADE→RESTRICT migration.
Out (stage 6): final grades, averages, Excel export, thematic grades. No printing, no undo, no multi-cell selection/paste.

## 2. Migration and models (agent A)
New revision on top of `4399f0e8a6d1`, hand-checked, symmetric `downgrade`.

| FK (convention name) | was | now |
|---|---|---|
| `fk_journals_class_id_classes` | CASCADE | RESTRICT |
| `fk_lessons_journal_id_journals` | CASCADE | RESTRICT |
| `fk_final_grades_journal_id_journals` | CASCADE | RESTRICT |
| `fk_lesson_entries_student_id_students` | CASCADE | RESTRICT |
| `fk_final_grades_student_id_students` | CASCADE | RESTRICT |

Unchanged: `lesson_entries.lesson_id` (CASCADE — deleting a lesson deliberately removes its cells), `classes.teacher_id`, `students.class_id`.
Index: drop `ix_lessons_journal_id`, create `ix_lessons_journal_semester_date` on `(journal_id, semester, lesson_date)` (explicit `Index` in `__table_args__`; remove `index=True`).

ORM: `SchoolClass.journals`, `Journal.lessons`, `Journal.final_grades` → `cascade="save-update, merge"`, `passive_deletes="all"` (the DB refuses; the ORM must not delete children or null FKs). `Lesson.entries` and `SchoolClass.students` keep `all, delete-orphan`. `Journal.lessons` order: `lesson_date, id`.

Existing tests:
- `tests/test_models.py::test_delete_class_cascades` → replace with (a) class with journal: `flush()` raises `IntegrityError`; (b) class with students only is deleted with its students.
- `test_delete_teacher_cascades_to_classes` → delete the fixture journal first; add a case "teacher with a journal → `IntegrityError`".
- `tests/test_class_service.py`: no changes expected (`ClassService.delete_class` / `delete_student` already refuse when journals/records exist; RESTRICT is a second line of defence). Do not edit `class_service.py` / `class_repository.py`. Run the file to confirm.

## 3. Shared contract — `src/journal/services/journal_types.py`
Created by the orchestrator BEFORE both agents start; neither agent edits it. See the file for the exact code (DTOs, errors, `semester_for_date`, `JournalApi` Protocol).

### Behaviour (A implements `JournalService(session)` in `services/journal_service.py` + `repositories/journal_repository.py`)
- Every method resolves ownership through `classes.teacher_id`; a foreign or missing object → `JournalNotFound` / `LessonNotFound` (never reveal existence).
- `list_journals`: sorted by `class_name_key`, then subject name; journals of archived classes only with `include_archived`.
- `list_journal_candidates`: non-archived class × subject pairs that have no journal yet.
- `create_journal`: duplicate → «Такий журнал уже існує»; archived class → «Клас в архіві — спершу поверніть його».
- `delete_journal`: only with no lessons and no final grades, else «У журналі є уроки чи оцінки — його не можна видалити».
- `get_grid`: lessons of that semester ordered by `(lesson_date, id)`; students = active by `position`, then archived students having at least one entry in this journal (Ukrainian alphabet). `semester` not in (1, 2) → `JournalError`.
- `create_lesson` / `update_lesson`: semester = `semester_for_date`; the date must fall inside the class's `school_year` (Sep–Dec of the first year, Jan–Jun of the second), else «Дата не належить навчальному року {year}». Topic trimmed, empty → `None`, >255 → error. Several lessons on one date allowed.
- `delete_lesson`: deletes the lesson with its entries (confirmation is a UI concern).
- `set_cell`: full-state idempotent upsert. `attendance="present"`, `grade=None`, empty comment → the row is deleted and `None` returned. Validation: grade 1–12 («Оцінка має бути від 1 до 12»); grade with `absent`/`sick` → «Відсутньому учню не можна поставити оцінку» (`late` + grade is fine); the student must belong to the journal's class and not be archived («Учень вибув — його клітинки лише для перегляду»); comment trimmed, max 500.
- All writes on an archived class → «Клас в архіві — журнал лише для перегляду».

## 4. Grade input rule (UI, agent B)
- `2`–`9`: commit that grade immediately. `0` alone: ignored.
- `1`: the cell shows a pending "1" and a single-shot `QTimer` (`GRADE_CHAIN_MS = 500`) starts. `0`/`1`/`2` on the same cell before timeout → commit 10/11/12. Timeout → commit 1. Any other key, current-cell change, focus loss or semester switch first flushes the pending value as 1, then proceeds. Exactly one `set_cell` call per resulting grade.
- A digit on an `absent`/`sick` cell sets attendance to `present` together with the grade. `н`/`х` clears the grade. `з` keeps it.
- `Del`/`Backspace`: attendance → present, grade → None; the comment stays (removed via F2).
- The cursor does not move after a commit.

## 5. UI (agent B)
Files: `ui/journals_page.py` (`JournalsPage(current_user, api_factory=None)` — `QStackedWidget`: list ↔ journal view), `ui/journal_grid.py` (model, header, delegate, table view), `ui/journal_dialogs.py`.
`api_factory: Callable[[], ContextManager[JournalApi]]`; the default opens `session_scope()` and yields `JournalService(session)` with a lazy import inside the function. UI imports only `journal_types`, `class_service.StudentInfo`, `journal.db.session_scope`. Follow `classes_page.py` conventions (`_call`, `_confirm`, `widgets.py` helpers, `refresh_icons`).

- **List**: cards «9-А · Математика», school year, lesson count; «Новий журнал» button (dialog with class and subject combos from candidates; no candidates → hint to create a class first); «Показати архівні» checkbox; empty state. Deleting a journal is in the journal view menu.
- **Journal view**: back button, title, segmented switcher «I семестр / II семестр» (default `semester_for_date(today)`, fallback 1), «Новий урок» (primary), inline error banner (`error="true"` label, hidden after 5 s), the table. Empty states: no students → «У класі немає учнів»; no lessons → «Уроків у цьому семестрі ще немає» with the button.
- **Table**: single `QTableView` + `JournalGridModel(QAbstractTableModel)`. Names live in the **vertical header** («1. Прізвище Ім'я», left-aligned, fixed width 240). Columns fixed width 56, single-cell selection, edit triggers disabled.
- **Column header**: custom `QHeaderView` subclass painting two lines — `dd.MM` and the type abbreviation (none / КР / ЛР / СР) — on a tinted background for non-regular types. Tooltip: full date, type name, topic. Double click or context menu → «Редагувати урок» / «Видалити урок».
- **Cells** (delegate): absent «н», sick «хв», late «з» or «з 9», grade as a number; soft background per mark; a comment is a small accent corner triangle plus tooltip. Archived students' rows muted and read-only. Archived class: whole grid read-only, lesson buttons hidden.
- **Keys** (`keyPressEvent` of the view, by `event.text()`, case-insensitive): digits as §4; `н`/`y` absent, `х`/`[` sick, `з`/`p` late (same mark again → present); `Del`/`Backspace` clear; `Enter`/`Return` down; `Tab`/`Shift+Tab` right/left; `F2` comment dialog (multi-line, 500 chars); `Ctrl+N` (shortcut scoped to the journal view) creates a regular lesson for today without a dialog, switches to its semester and selects its first cell.
- **Autosave**: the model changes a cell only after `set_cell` succeeds. `JournalError` → cell keeps old value, banner shows the message; other exception → `logging.exception` + generic text.
- **Lesson dialog** (new/edit): date (`QDateEdit`, calendar popup, default today), type combo (Звичайний урок / Контрольна робота / Лабораторна робота / Самостійна робота), topic (optional).
- **Lesson delete**: `entry_count == 0` → ordinary confirm; otherwise a dialog stating the number of marks, delete button enabled only after typing `видалити`.
- **Theme tokens** (already added by the orchestrator to `theme.py`; B uses only `theme.color()`): `mark_absent`, `mark_absent_soft`, `mark_sick`, `mark_sick_soft`, `mark_late`, `mark_late_soft`, `lesson_test_soft`, `lesson_lab_soft`, `lesson_independent_soft`.
- **Fake**: `tests/fakes/fake_journal_service.py` — `FakeJournalService` implementing `JournalApi` in memory with the same validation messages for `set_cell`, a `calls` list, and a `fail_next: JournalError | None` hook.

## 6. File ownership
| Owner | Files |
|---|---|
| A | `migrations/versions/<new>.py`, `models/journal.py`, `models/school_class.py`, `repositories/journal_repository.py`, `services/journal_service.py`, `tests/test_models.py`, `tests/test_journal_service.py` |
| B | `ui/journals_page.py`, `ui/journal_grid.py`, `ui/journal_dialogs.py`, `tests/fakes/*`, `tests/ui/*` |
| Orchestrator | `services/journal_types.py`, `ui/theme.py`, `ui/main_window.py`, `ui/icons.py`, `ui/widgets.py`, `requirements*.txt`, docs |

## 7. Tests
**A** (`session` fixture): `semester_for_date` boundaries incl. July; ownership for every method; journal create/duplicate/archived/delete rules; lesson date outside the school year; two lessons on one day and their order; `get_grid` content, semester filter, archived-student rule; `set_cell` insert/update/idempotence/row deletion on empty state, grade range, grade + absent, late + grade, foreign and archived student, comment limits; `delete_lesson` removes entries; RESTRICT tests from §2. `alembic upgrade head` on a clean DB must pass (CI).
**B** (`pytest-qt`; `tests/ui/conftest.py` sets `QT_QPA_PLATFORM=offscreen` before Qt imports): every key from the map against the fake; 1→10/11/12 chain, timeout → 1, flush on navigation, one call per grade; digit on an absent cell; Del keeps the comment; Enter/Tab at the edges; failed save keeps the old value and shows the banner; read-only archived rows/class; Ctrl+N creates a lesson; typed confirmation gates deletion; header text for each lesson type.

## 8. Done criteria
- `alembic upgrade head` and `downgrade -1` work; full `pytest` green.
- UI files import neither `sqlalchemy`, `journal.models` nor `journal.repositories`; no colour literals outside `theme.py`.
- No agent touched a file outside its row in §6.
- Offscreen: create journal → Ctrl+N → enter `н`, `х`, `з`, 7, 10, 12, comment → reopen: persisted; light and dark screenshots in `docs/screenshots`.
- Fable review verdict `APPROVE`.
