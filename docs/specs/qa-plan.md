# QA sweep plan (decided by the Fable reviewer, 2026-11-12)

The author asked to check absolutely everything new, including design. Branch `chore/qa-sweep`; QA agents do NOT change `src/`. Fixes go to a separate `fix/qa-findings` PR.

## Common rules (both agents)
- `QT_QPA_PLATFORM=offscreen` (+ `QT_QPA_FONTDIR=C:\Windows\Fonts`); no windows on the author's screen.
- Database: `TEST_DATABASE_URL` only — assert the database name ends with `_test`. Never read the app database; never print `.env` values.
- Everything in ONE outer transaction that is rolled back (pattern of the `session` fixture in tests/conftest.py); nothing committed. Redirect `session_scope`: patch `journal.db.session_scope` AND the names imported at module top (e.g. `journal.ui.classes_page.session_scope`, `journal.ui.class_dialogs.session_scope`, `journal.ui.journals_page.session_scope`, `journal.ui.rollover_dialog.session_scope`, `journal.ui.settings_cards.session_scope`) — check each module's imports.
- REAL services, not fakes. Fictional data generated in the script: teacher «Демо Викладач», ~35 fixed fictional student names («Демченко Олена», «Тестовий Іван», …), classes 5-А…11-Б. Freeze "today" by parameter or monkeypatch.
- Patch `QMessageBox`/dialog `exec` where needed so nothing blocks (modal dialogs hang offscreen). Use `timeout` on every run.

## Agent A (Sonnet) — screenshot sweep
Owns `scripts/qa/screens.py`, `docs/screenshots/qa/*.png`, and section 1 of the report.
- `widget.grab()` at 1280×800 → `NN_screen_state_{light|dark}.png`; every state in both themes; main screens also once at minimum window size (light). Limit ~90 PNGs.
- States: (1) Login/Register incl. error. (2) Classes list: empty; six classes; with archived shown. (3) Class detail: no students; 30 students; withdrawn students; archived class with restore button; 150-char student name; 20-char class name. (4) Class dialogs: new class, add student, import, archive/delete confirmations. (5) Journals list: empty; cards; «Показати архівні»; 50-char subject name. (6) New journal dialog incl. "nothing to create". (7) Grid: no students; no lessons; 30 students × 25 lessons scrolled left/right; grades 1–12, «н», «хв», «з», «з 9», comment marker; withdrawn row; selected cell; semester II; archived journal (subtitle «· клас в архіві») with «Ще» menu and «Видалити журнал» disabled. (8) Lesson panel: empty; 25 lessons; 255-char topic; «тема не вказана»; test lesson; context menu. (9) Lesson dialog: new; edit; calendar popup open; vacation-date error; out-of-year error. (10) Delete lesson; delete journal (simple and typed «видалити»). (11) Settings: theme card; SemestersCard default, month popup open, validation error, saved status, conflict with 3 and with 13 lessons («і ще 3»); SubjectsCard ~20 subjects, duplicate error. (12) JournalSettingsDialog: active (disabled, «Змінюється в Налаштуваннях»); archived (editable); conflict. (13) RolloverDialog: one line; eight mixed lines with checkbox; without checkbox; 20-char class name.
- Automatic checks written to the report: visible QLabel/QPushButton/QCheckBox/QComboBox whose text is wider than its rect (fontMetrics) or sizeHint exceeds size → "clipped"; WCAG contrast from theme.py tokens (text/surface, muted/surface, accent_text/accent, danger/surface) in both themes; grep `src/journal/ui` (excluding theme.py) for `#[0-9a-fA-F]{3,8}`, `QColor(`, `rgb(`.
- Then look at EVERY PNG once against: clipping/overlap; alignment and uneven margins; unreadable contrast; light popup/menu/calendar in dark theme; missing combo arrow; empty-state texts; long names/topics (elide or wrap); archived states; visible focus.

## Agent B (Sonnet) — end-to-end scenarios
Owns `tests/e2e/__init__.py`, `tests/e2e/conftest.py` (if needed), `tests/e2e/test_qa_scenarios.py`, and section 2 of the report. pytest-qt offscreen, real pages and services on journal_test. ≤ 12 tests. Run only this file (orchestrator runs full pytest at the end).
- S1: create class → add students → import → mark one withdrawn → new journal → Ctrl+N → keyboard entry (digits; `1` then `0/1/2` → 10/11/12; `н`, `х`, `з`, Del, F2 comment, Enter down, Tab right) → verify through services.
- S2: lesson panel — edit type and topic; delete a lesson with marks; numbering per semester.
- S3: Settings — II from December moves a December lesson into II; conflicting change saves nothing and combos revert.
- S4: archive a class → add a past-date lesson and a grade in its journal; journal deletion disabled and refused; change boundaries in «Налаштування журналу»; restore → resync; restore with conflict shows the lesson list.
- S5: rollover with today = 1 Aug: «Пізніше» changes nothing; «Гаразд» with checkbox creates new class, students, journals and refreshes both pages; second run → no dialog. Edge classes: 11-Б, «Гурток», existing target, 20-char «9…» name, «09-А» with «9-А».
- S6: delete a journal with the typed word; a class with journals takes the archive path.
- S7: switch theme with a journal open; no exception; grid repaints.
- S8: keyboard only — Tab order, Enter = default button, Esc in every dialog; default in confirmations is «Скасувати».
- S9: another teacher's class/journal/lesson ids → «не знайдено».
- S10: after all scenarios the log file contains no student names.
- A failing scenario is kept as `xfail(strict=True)` with the finding id.

## Output
`docs/reviews/2026-11-12-qa-report.md`: environment and commit; section 1 (screens) and section 2 (scenarios) as tables `ID | severity | screen/scenario | what | screenshot | suggested fix`; «Nitpicks» (≤ 10 lines); «Checked, OK». Agent A creates the file with section 1; agent B appends section 2 in a separate file `docs/reviews/2026-11-12-qa-report-e2e.md` (orchestrator merges them).

## Severity
- **P1** (blocks handing the app to the teacher): crash/traceback; wrong or lost data; refusal without an understandable reason; real/personal data in logs or screenshots; a roadmap keyboard key not working.
- **P2** (fix in `fix/qa-findings`): clipped/overlapping text; text contrast < 4.5:1 (< 3:1 large text and control borders); theme leak; stale page after an action; control unreachable by keyboard or no visible focus; wrong/misleading Ukrainian text; missing empty state; leftover «лише для перегляду» for journals.
- **Nitpick**: spacing ≤ 4 px; wording/icon taste; items already in docs/assumptions.md; feature ideas.

## Then
Fable triage (one pass) → fix list → one Sonnet agent fixes P1/P2 in `fix/qa-findings` → Fable review → merge.
