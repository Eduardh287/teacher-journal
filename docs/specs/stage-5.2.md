# Stage 5.2 — Semester settings & school-year rollover

*Spec by the Fable reviewer, decisions by the author (2026-11-12). Overrides the hardcoded Sep–Dec / Jan–Jun rule of stage 5.*

## 0. Author's answers (binding)
- Boundaries are set by MONTH in Settings; defaults I = Sep–Dec, II = Jan–Jun; other months are vacation (no lessons in vacation — confirmed).
- Journals of non-archived classes follow the global setting; archived journals keep their boundaries and can be changed only manually per journal.
- A boundary change that would put an existing lesson into vacation is REFUSED, listing the lessons.
- Rollover: automatic with a confirmation dialog, offered from **1 August** (`semesters.rollover_due`). 9-А → NEW class 10-А for the next year with the same active students; old class + journals archived unchanged; 11th grade and classes without a leading number → archive. The dialog has a checkbox **«Створити такі самі журнали для нових класів»** (`apply(..., copy_journals=True)` creates empty journals for the same subjects). Re-formed classes (renamed letter/roster) are fixed by the teacher afterwards — no editing in the dialog.
- Validation (orchestrator, follows from "rollover from August"): semester I starts in Aug or later, semester II ends before August.

## 1. Contract (already committed by the orchestrator — do not change signatures without asking)
- `services/semesters.py`: `SemesterBoundaries` (`validate`, `semester_of_month`, `semester_for`, `calendar_year`, `contains`, `label`), `DEFAULT_BOUNDARIES`, `SemesterError`, `VacationDateError`, `MONTHS_UA`, `rollover_due`, `next_school_year`.
- `services/journal_types.py`: `semester_for_date(d, boundaries=DEFAULT)`; `JournalInfo.boundaries`; `LessonConflict`; `SemesterConflict(JournalError).conflicts`; `JournalApi.set_journal_semesters`.
- `services/settings_service.py` (`get_semesters`, `set_semesters`), `services/rollover_service.py` (`RolloverItem`, `plan`, `apply(copy_journals)`): stubs to implement.

## 2. Schema (one Alembic revision, agent A)
`teachers` and `journals` get `s1_start_month`, `s1_end_month`, `s2_start_month`, `s2_end_month` (`SMALLINT NOT NULL`, server_default 9/12/1/6, CHECK 1..12). `teachers.*` = global setting; `journals.*` = snapshot (equal to global for non-archived classes, frozen for archived). Backfill = defaults (stored `lessons.semester` stays valid). `lessons.semester` is kept and recomputed whenever a journal's boundaries change.

## 3. Services (agent A)
- `SettingsService.set_semesters`: validate; for every journal of a non-archived class recompute each lesson's semester and check `contains(school_year, date)`; any failure → `SemesterConflict` (sorted by class, subject, date), nothing saved; else update teacher row, journal snapshots, `lessons.semester`; return number of journals updated.
- `JournalService`: `create_journal` copies the teacher's boundaries; `_check_date` uses the journal snapshot (`contains` + `semester_for`); `JournalInfo.boundaries` filled; `set_journal_semesters` only for an archived class (else `JournalError("Межі семестрів журналу в роботі змінюються в Налаштуваннях")`), same conflict rule — the single write allowed on an archived journal; `delete_journal` on an archived class refused with the archived message.
- `ClassService.set_class_archived(archived=False)`: resync the class's journals to the global setting; conflict refuses the restore (`SemesterConflict`).
- `ClassService` default year: `default_school_year`/`school_year_choices` unchanged (already switch in August).
- `RolloverService.plan`: candidates = non-archived classes with `rollover_due(school_year, today)`; name `^(\d{1,2})(.*)$` with n < 11 → promote to `f"{n+1}{suffix}"` in `next_school_year`; else archive. `target_exists` if that class already exists (any archive state) → only archive the old one. `apply` recomputes the plan in one transaction: create class, copy ACTIVE students as new rows (renumber), optionally create empty journals for the same subjects (teacher's current boundaries), archive the old class. Idempotent.

## 4. UI
- **B:** `ui/settings_cards.py` — `SemestersCard` (four month combos «I семестр: з … по …», «II семестр: з … по …», hint «Інші місяці — канікули», «Зберегти», inline error; on `SemesterConflict` list «9-А · Алгебра — 15.01.2027» (first 10, then «і ще N») and revert combos; success «Збережено. Оновлено журналів: N») and `SubjectsCard` moved out of `main_window.py`; both take an injectable `service_factory`. `main_window.py` mounts both cards.
- **C:** journal «Ще» → «Налаштування журналу» (`JournalSettingsDialog`: same combos; editable only for an archived class, otherwise disabled with «Змінюється в Налаштуваннях»; conflict list); «Видалити журнал» disabled for archived classes; `journals_page.open_journal` uses `info.boundaries.semester_for(today)` (fallback 1 in vacation). `ui/rollover_dialog.py` + `app.py`: after `window.show()`, `QTimer.singleShot(0, ...)` → plan; empty → nothing; else «Навчальний рік завершено» with lines «9-А → 10-А (2027-2028), учнів: 28», «9-Б → архів (10-Б уже існує)», «11-Б → архів», checkbox «Створити такі самі журнали для нових класів» (shown only if some promote item has subjects), buttons «Гаразд» / «Пізніше»; «Гаразд» → apply, refresh classes & journals pages; errors → message + log without names.

## 5. File ownership
| Agent | Model | Files |
|---|---|---|
| A | Sonnet | `models/*`, `migrations/versions/*`, `repositories/*`, `services/settings_service.py`, `services/rollover_service.py`, `services/journal_service.py`, `services/class_service.py`, `tests/test_*.py` (root tests), `docs/specs/stage-5.1.md`, `docs/assumptions.md` |
| B | Sonnet | `ui/settings_cards.py`, `ui/main_window.py`, `tests/ui/test_settings_cards.py` |
| C | Sonnet | `ui/journals_page.py`, `ui/journal_dialogs.py`, `ui/rollover_dialog.py`, `app.py`, `tests/fakes/*`, `tests/ui/conftest.py`, `tests/ui/test_journal_settings.py`, `tests/ui/test_rollover_dialog.py`, other `tests/ui/test_journal*.py` only if a message change breaks them |
| Orchestrator | — | `services/semesters.py`, `services/journal_types.py`, `ui/theme.py`, `docs/specs/stage-5.2.md` |

## 6. Tests
semesters (defaults, wrapped valid range, overlap/order/August rule rejected, vacation, contains, rollover_due edges); migration up/down + backfill; set_semesters (recompute moves a lesson, conflict saves nothing and lists, archived untouched, other teacher untouched); set_journal_semesters (archived OK, active refused, conflict); restore class resync + conflict; create_journal copies; delete_journal on archived refused; rollover (promote copies only active students as new ids 1..N; old class+journals archived, grades intact; 11 → archive; non-numeric → archive; target exists; copy_journals creates empty journals; second apply no-op; nothing before 1 August; custom boundaries). UI offscreen with fakes for cards, journal settings dialog, rollover dialog («Гаразд» calls apply with the checkbox value, «Пізніше» does not, empty plan → no dialog).

## 7. Done
Full pytest green; `alembic upgrade head` and `downgrade -1` clean on journal_test; app starts; no colour literals; light/dark offscreen screenshots of the card and both dialogs; Fable APPROVE.
