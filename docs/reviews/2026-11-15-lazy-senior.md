# Аудит «лінивого сеньйора»: teacher-journal

Дата: 15.11.2026. Обсяг: `src/journal/**`, `scripts/`, `packaging/build.ps1`, `migrations/env.py`, `tests/**`.
Жоден файл проєкту не змінено. Що запускалось: повний `pytest --durations=70` (828 passed, **22 хв 54 с**),
два контрольні прогони з тимчасовим плагіном зі scratchpad (перевірка ідеї T1), `python -X importtime`.
Усе — лише на `journal_test`, offscreen. Оцінки «−N рядків» приблизні; перевірена експериментом лише T1.

## Підсумок: 5 найбільших виграшів

1. **T1 — тести 22:54 → ~1:45.** Віджети з попередніх тестів не знищуються, а autouse-фікстура на кожен UI-тест
   перезастосовує тему до всіх них (setup 6–7 с навіть у тестів чистих функцій). Виправлення — 3 рядки у фікстурі.
   Перевірено: `tests/ui` 312 тестів за **28 с** (було ~18 хв), решта 516 тестів — 75 с.
2. **S1+S2 — один базовий діалог і спільні картка / порожній стан / підтвердження.** Зараз три однакові
   базові діалоги, дві однакові картки, чотири порожні стани, два `_confirm`. Близько −230 рядків UI.
3. **D1–D3 — мертвий код:** залишки режиму `read_only`, `MainWindow._empty_state`, `DeleteLessonDialog`,
   запасні гілки «для старих тестів». Близько −130 рядків, жодної зміни поведінки.
4. **A1 — запуск: −0,8 с з 3,6 с імпорту.** `openpyxl` імпортується при старті заради кнопки «Експорт».
   Відкладений імпорт — 1 рядок.
5. **A2+A3 — журнал:** `get_grid` робить ~11 запитів там, де досить 6 (ті самі уроки, стовпчики й відмітки
   читаються двічі), а кожне натискання клавіші вантажить відмітки всього класу заради одного рядка.

---

## Швидкість (тести)

### T1. Витік віджетів + тема на кожен тест — головна причина 16–27 хв
- **Де:** `tests/ui/conftest.py:20-24` (`_fast_chain`), `tests/e2e/conftest.py:74-93` (`_isolation`).
- **Було:** pytest-qt закриває віджет через `close()` + `deleteLater()`, але без запущеного циклу подій
  відкладене видалення не виконується — віджети всіх попередніх тестів живуть до кінця сесії. Autouse-фікстура
  на кожен тест викликає `theme.apply_theme()` → `app.setStyleSheet()` перестилізовує їх усі. Час росте квадратично:
  наприкінці `setup` = 6–7 с навіть у `test_text_contrast` (чиста функція), `test_apply_theme_renders_images` — 14–16 с.
- **Стане:**
  ```python
  @pytest.fixture(autouse=True)
  def _fast_chain(monkeypatch, qapp):
      monkeypatch.setattr(journal_grid, "GRADE_CHAIN_MS", 80)
      if theme.current_theme() != "light" or not qapp.styleSheet():
          theme.apply_theme(qapp, "light")
      yield
      QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)  # справді знищити віджети тесту
  ```
  Те саме — у teardown `_isolation` в e2e.
- **Виграш (заміряно):** `tests/ui` 312 passed за 28 с; `tests --ignore=tests/ui` 516 passed за 75 с; живих віджетів
  наприкінці — 0. Разом ~1 хв 45 с замість 22 хв 54 с. Тайм-аут CI 30 хв можна зменшити, `pytest-xdist` не потрібен.
- **Ризик:** низький (усі 828 тестів пройшли з виправленням). **Обсяг:** S.

### T2. Справжній Argon2 у ~50 тестах авторизації
- **Де:** `tests/test_auth_security.py`, `tests/test_auth_service.py`, `tests/ui/test_auth_ui.py`; `auth_service.py:40-43`.
- **Було:** кожен hash/verify ~85–100 мс; тести блокування роблять по 5–12 перевірок (0,4–1,2 с кожен, разом ~20 с із 75 с).
- **Стане:** autouse-фікстура в `tests/conftest.py`: `monkeypatch.setattr(auth_service, "_hasher", PasswordHasher(time_cost=1, memory_cost=8, parallelism=1))`
  і `_DUMMY_HASH` тим самим хешером. Один тест лишити на справжніх параметрах.
- **Виграш:** ~−15–20 с. **Ризик:** низький. **Обсяг:** S.

### T3. Три запуски окремого Python для перевірки парсера аргументів
- **Де:** `tests/test_reset_password_script.py:94-96` (`test_refuses_password_from_argv[extra0..2]`, 1,7–1,9 с кожен).
- **Стане:** два з трьох варіантів — у процесі через `main(argv)` (парсер БД не чіпає), один лишити як справжній запуск.
- **Виграш:** ~−3,5 с. **Ризик:** низький. **Обсяг:** S.

### T4. Однакові фікстури в п'яти файлах тестів сервісів
- **Де:** `make_teacher` / `teacher` / `svc` / `classes` / `journal` у `test_class_service.py:35-48`, `test_journal_service.py:26-76`,
  `test_journal_grades.py:43-56`, `test_semester_settings.py:19-51`, `test_rollover_service.py:19-45`.
  У `tests/conftest.py:80-101` уже є `teacher_class`, але ним користується лише `test_models.py`.
- **Стане:** одна пара `teacher` + `make_class` у `tests/conftest.py`.
- **Виграш:** ~−60 рядків, читабельність. **Ризик:** низький. **Обсяг:** M.

---

## Спрощення

### S1. Три однакові базові діалоги → один
- **Де:** `journal_dialogs.py:52-89` (`_ApiDialog`), `class_dialogs.py:36-86` (`_ClassDialogBase`), `auth_dialogs.py:100-164` (`_AuthDialog`);
  той самий каркас вручну — `journal_dialogs.py:302-309, 352-359`, `export_dialog.py:49-58, 75-83`, `rollover_dialog.py:71-76`, `auth_dialogs.py:50-52`.
- **Було:** заголовок вікна, поля 32/28, `EmptyTitle`, рядок помилки (6 копій `setProperty("error", True)`), `show_error`,
  `run_service` (try / with / except доменна помилка / except Exception) — тричі; кнопка `setDefault + setMinimumHeight(40) + connect` — 10 разів.
- **Стане:** `widgets.FormDialog(title)` з `error_label`, `show_error()`, `add_submit(text, slot)` і
  `run(action, scope, error_cls)`; нащадки передають лише свій сервіс і клас помилки. `JournalSettingsDialog._on_save`
  (`journal_dialogs.py:485-511`) теж переходить на `run`.
- **Виграш:** ~−100 рядків. **Ризик:** низький–середній (багато UI-тестів на діалоги). **Обсяг:** M.

### S2. Сторінки «Класи» і «Журнали»: картка, порожній стан, підтвердження, сітка
- **Де:** `_ClassCard` `classes_page.py:58-93` ≡ `_JournalCard` `journals_page.py:85-116`; `_confirm` `classes_page.py:144-152` ≡
  `journals_page.py:181-189`; порожній стан ×4: `classes_page.py:196-230, 370-384`, `journals_page.py:231-248, 403-421`;
  сітка карток `classes_page.py:243-259` ≡ `journals_page.py:256-272`; шапка списку `classes_page.py:158-194` ≡ `journals_page.py:195-229`.
- **Стане:** у `widgets.py`: `EntityCard(title, subtitle, footer, archived)`, `confirm(parent, text, accept_text)`,
  `empty_state(title, hint="", action=None)`, `card_grid(scroll, cards, columns=3)`.
- **Виграш:** ~−130 рядків. **Ризик:** низький. **Обсяг:** M.

### S3. П'ять копій відмінювання після числа
- **Де:** `journals_page.py:72-82`, `journal_grid.py:84-94`, `classes_page.py:45-55`, `class_dialogs.py:286-294`, `rollover_dialog.py:40-46`.
- **Стане:** `plural(n, "урок", "уроки", "уроків")` у `services/grid_text.py`.
- **Виграш:** ~−35 рядків, одне правило замість п'яти. **Ризик:** низький. **Обсяг:** S.

### S4. Два редактори меж семестрів і два форматувальники конфліктів
- **Де:** `settings_cards.py:65-69, 110-159` і `journal_dialogs.py:435-483`; `format_conflicts` `settings_cards.py:72-81` ≡
  `conflict_text` `journal_dialogs.py:414-421` (ліміт 10 теж двічі: `MAX_CONFLICTS_SHOWN`, `CONFLICT_LIMIT`).
- **Стане:** віджет `SemesterBoundsEditor` з `boundaries()` / `set_boundaries()` / `setEnabled()`; один `conflict_text`.
- **Виграш:** ~−50 рядків. **Ризик:** низький. **Обсяг:** S–M.

### S5. Чотири картки налаштувань збирають той самий каркас вручну
- **Де:** `settings_cards.py:99-126, 216-240, 320-360, 503-532`; `_show_error` ×3 (172, 373, 541), `_show_status`.
- **Було:** `setObjectName("Card")`, поля 24, заголовок, підказка, `status`, `error` — у кожній картці; при цьому `widgets.card()` уже є.
- **Стане:** `class SettingsCard(QFrame)` із `__init__(title, hint)`, `show_status()`, `show_error()`.
- **Виграш:** ~−45 рядків. **Ризик:** низький. **Обсяг:** S.

### S6. П'ять фабрик «транзакція + сервіс»
- **Де:** `journals_page.py:63-69`, `settings_cards.py:39-54`, `rollover_dialog.py:31-37`, `scripts/reset_password.py:22-26`,
  плюс прямі `with session_scope() as session: Service(session)` у `classes_page.py:123`, `class_dialogs.py:70`, `auth_dialogs.py:28`.
- **Стане:** один помічник у шарі UI (`ui/service_scope.py`), щоб не порушувати правило «UI торкається БД лише через `session_scope()`»:
  ```python
  @contextmanager
  def service_scope(service_cls):
      with session_scope() as session:
          yield service_cls(session)
  ```
  Побічний виграш: e2e-фікстурі (`tests/e2e/conftest.py:84-86`) досить підмінити одне місце замість обходу `sys.modules`.
- **Виграш:** ~−30 рядків. **Ризик:** низький. **Обсяг:** S.

### S7. Дублі всередині `journal_service.py`
- **Де й що:**
  - `_clean_topic` / `_clean_homework` / `_clean_comment` (657-675) → `_clean(text, limit, label)`;
  - `_lesson_type` (650) і `_column_kind` (633) → `_enum(cls, code, message)`;
  - перевірка учня тричі (369-373, 410-412, 428-432) → `_own_student(class_id, student_id, editable)`;
  - перевірка оцінки двічі (374-377, 436-437) → `_check_grade`;
  - «прив'язати стовпчик до уроку» тричі (247-249, 306-308, 336-338) → `_attach(column, lesson)`;
  - `withdrawn_with_entries` / `withdrawn_with_extra_grades` (`journal_repository.py:142-158`) → один метод з параметром моделі;
  - у `update_lesson` (238-245) п'ять тимчасових змінних лише для присвоєння.
- **Виграш:** ~−45 рядків. **Ризик:** низький (48+50 тестів сервісу). **Обсяг:** S.

### S8. `apply_boundaries`: два однакові цикли
- **Де:** `settings_service.py:25-40` (уроки) і `46-61` (стовпчики) — відрізняються лише полем дати.
- **Стане:** один цикл по `[(lesson, lesson.lesson_date), …, (column, column.after_date), …]`.
- **Виграш:** ~−22 рядки. **Ризик:** низький. **Обсяг:** S.

### S9. `build_export_table`: вид стовпця розбирається тричі
- **Де:** `export_service.py:175-189` (чи в періоді), `193-207` (заголовок), `215-239` (клітинка). У другому циклі `next(...)` шукає
  урок перебором, хоча словники `lessons` / `extras` побудовано у першому. Обгортки `_semester_last_day` (120) і `_lesson_header` (144) нічого не додають.
- **Стане:** одна функція `_describe(grid, column) -> (day, ExportColumn, key)`, викликається раз на стовпець; функція зі 105 рядків стає ~70.
- **Виграш:** ~−25 рядків. **Ризик:** низький–середній (19 тестів). **Обсяг:** S.

### S10. Конфіг Alembic і шляхи збираються в кількох місцях
- **Де:** `Config(alembic.ini) + script_location` — `embedded_db.py:477-481`, `498-500`, `backup_service.py:149-151`, `tests/conftest.py:29-32`;
  `(ascii_safe(root) or root) / "bin"` — `embedded_db.py:535-538` і `backup_service.py:226-227`;
  корінь даних (`JOURNAL_DATA_DIR` → `%LOCALAPPDATA%` → home) — `embedded_db.requested_root` (130-138) і `logging_setup.log_dir`;
  `pg_ctl stop` — `embedded_db.py:447-449` і `464-466`.
- **Стане:** `embedded_db.alembic_config(url=None)`, `embedded_db.pg_bin_dir()`, `log_dir()` = `requested_root() / "logs"`, `_pg_stop()`.
- **Виграш:** ~−25 рядків. **Ризик:** низький. **Обсяг:** S.

### S11. Те, що вже вміють stdlib і Qt
- `export_dialog.py:37-42` (`_qdate` / `_pydate`), `journal_dialogs.py:184-185, 276-277`: PySide6 сам приймає `datetime.date`
  у `setDate()` і має `QDate.toPython()` (перевірено) → помічники зайві.
- `auth_service.py:85` `-(-seconds // 60)` і `:159` `int(-(-remaining // 1))` → `math.ceil(...)`.
- `embedded_db.py:199-201` `generate_secret` → `secrets.token_hex(16)` (ті самі 32 символи; наявні `db.secret` не зачіпає).
- `backup_service.py:326-347`: три гілки `except` з однаковим `part.unlink(missing_ok=True)` → одна в `finally`.
- `backup_service.py:360` `(parse_backup_name(p) or (0, ""))[1] == "auto"` → `directory.glob("journal_*_auto.dump")`.
- `backup_service.py:28, 31-33, 42-47`: перелік видів копій записано тричі → `KINDS = tuple(KIND_TITLES)`, регулярний вираз будується з нього.
- Навчальний рік: `f"{y}-{y + 1}"` і `int(school_year[:4])` у `class_service.py:73-82`, `semesters.py:91-102`, `rollover_service.py:108, 143-146`;
  місяць `8` у `class_service.py:75` при наявному `ROLLOVER_MONTH` → дві функції в `semesters.py`.
- **Виграш:** ~−30 рядків. **Ризик:** низький. **Обсяг:** S.

### S12. Зайва обережність через `getattr`
- **Де:** `rollover_dialog.py:52, 82` (`years_skipped` — звичайне поле dataclass), `137, 150-157`; `settings_cards.py:391, 418` і
  `backup_dialogs.py:123` (атрибути завжди є в `BackupService`); `journal_dialogs.py:241` (`_saved_inputs` задано в `__init__`);
  `main_window.py:160` (`journals_page` створено раніше за навігацію); `auth_service.py:161` — параметр `username` у `_register_failure` не використовується.
- **Стане:** пряме звернення до атрибутів; `_refresh_pages` — два рядки. Фейкові вікна в `tests/ui/test_rollover_dialog.py:47` отримають ті самі атрибути.
- **Виграш:** ~−12 рядків, чесніші типи. **Ризик:** низький. **Обсяг:** S.

### S13. Фейковий сервіс повторює бізнес-логіку (найбільший дубль, але дорогий)
- **Де:** `tests/fakes/fake_journal_service.py` (494 рядки) + `tests/test_fake_journal_order.py` (54) + `JournalApi` `journal_types.py:186-279` (95).
- **Було:** фейк заново реалізує округлення (`half_up`), порядок стовпчиків, перевірки дат і довжин — друга копія правил сервісу,
  яку теж доводиться тестувати.
- **Стане (дешево):** фейк викликає `grade_calc` і чисті функції порядку з сервісу, а не власні копії (−80 рядків).
  **Стане (радикально):** UI-тести працюють на справжньому `JournalService` у транзакції з відкатом, як уже роблять e2e;
  фейк і Protocol зникають (−640 рядків). Після T1 запас швидкості на це є.
- **Ризик:** середній / високий. **Обсяг:** M / L. Радикальний варіант — рішення автора.

---

## Читабельність

### R1. `JournalHeaderView.paintSection` і делегат клітинок
- **Де:** `journal_grid.py:350-410` — блок «шрифт 9 жирний → верхній рядок → шрифт 8 → нижній рядок» тричі (368-386, 387-393, 394-409);
  `416-495` — метод на 80 рядків; словники кольорів створюються на кожну клітинку (426, 449).
  Відтінки типів уроків записано двічі: `journal_grid.py:65-78` і `lesson_panel.py:40-46, 289`.
- **Стане:** `_draw_two_lines(painter, rect, top, bottom="")`; делегат = `_fill` + `_draw_text` + `_draw_marks`; словники — константи модуля,
  відтінки — в одному місці.
- **Виграш:** ~−35 рядків. **Ризик:** низький. **Обсяг:** S.

### R2. `_build_journal_view` на 118 рядків
- **Де:** `journals_page.py:283-401`; кнопка-сегмент із запасом ширини під жирний шрифт — двічі (309-319, 322-328), третій сегмент — `main_window.py:234-246`.
- **Стане:** `_build_toolbar()`, `_build_grid_area()`, `_build_shortcuts()` + `widgets.segment_button(text)`.
- **Виграш:** ~−15 рядків, метод читається з екрана. **Ризик:** низький. **Обсяг:** S.

### R3. Імпорт текстів через посередника
- **Де:** `journal_dialogs.py:23-27` реекспортує `LESSON_TYPES` / `EXTRA_COLUMN_TYPES` із `services/grid_text` (`noqa: F401`);
  `lesson_panel.py:27` бере їх із `journal_dialogs`, `journal_grid.py:22-29` — теж із `noqa`.
- **Стане:** усі імпортують прямо з `journal.services.grid_text`; обидва `noqa` зникають.
- **Ризик:** низький. **Обсяг:** S.

### R4. Контекстні меню з подвійним розбором
- **Де:** `journal_grid.py:739-756`, `lesson_panel.py:416-441` — спершу `if` для створення пунктів, потім такий самий `if`, щоб зрозуміти, який натиснуто.
- **Стане:** `menu.addAction("Редагувати урок", lambda: self.lesson_edit_requested.emit(entry.id))` — Qt сам викликає обробник.
- **Виграш:** ~−15 рядків. **Ризик:** низький–середній (тести підміняють `QMenu.exec`). **Обсяг:** S.

### R5. Два способи логувати помилки UI
- **Де:** `logging.exception(...)` — `journals_page.py:165`, `classes_page.py:139`, `journal_dialogs.py:86, 507`, `class_dialogs.py:76`,
  `settings_cards.py:166, 193, 248, 262, 558`, `auth_dialogs.py:161`, `rollover_dialog.py:129, 142`; `log_failure(...)` — копії та експорт.
- **Було:** `logging_setup.log_failure` існує саме тому, що текст винятку може містити дані, але половина UI пише в журнал повний текст.
- **Стане:** скрізь `log_failure` (після S1 це одне місце в `FormDialog.run`).
- **Виграш:** послідовність і менше ризику потрапляння імен у журнал. **Ризик:** низький. **Обсяг:** S.

### R6. Дрібниці
- `migrations/env.py`: ~25 рядків шаблонних англомовних коментарів Alembic → файл на ~35 рядків.
- `app.py`: `if sys.stdout: print(...)` чотири рази в `run_smoke` / `run_stop_server` → `_say(message)`; невикористаний `from pathlib import Path`.
- `xlsx_writer.py:113-117` і `140-144` — однакове налаштування друку → `_landscape(ws, title_rows)`; стиль заголовка тричі (64-72, 77-85, 124-129) → `_head(cell, fill)`.
- `BackupService.__init__` (`backup_service.py:188-218`): 11 параметрів, 7 із них — лише для тестів, з двома різними стилями значень за замовчуванням.
- **Ризик:** низький. **Обсяг:** S.

---

## Швидкість (застосунок)

### A1. `openpyxl` імпортується під час запуску
- **Де:** `export_dialog.py:26` → `xlsx_writer.py:10-15`; ланцюжок `app → main_window → journals_page → export_dialog`.
- **Було (importtime, другий прогін):** `journal.app` 3576 мс, з них `openpyxl` 808 мс, `sqlalchemy` 1231 мс.
- **Стане:** `from journal.services.xlsx_writer import write_export` усередині `export_journal()`.
- **Виграш:** ~−0,8 с запуску (22 % часу імпорту). Ще ~80 мс: `_DUMMY_HASH` рахується при імпорті `auth_service.py:43` — можна лінивим.
- **Ризик:** низький (тести підміняють `export_dialog.write_export` — перевірити). **Обсяг:** S.

### A2. `get_grid`: ті самі дані читаються двічі
- **Де:** `journal_service.py:154-201` + `_computed` `515-568`.
- **Було:** `all_lessons` двічі (158, 520), `extra_columns` двічі (176, 526), відмітки двічі (173 — семестр, 523 — увесь рік),
  `lesson_counts([journal_id])` (174) рахує те, що вже є як `len(all_lessons)`, `entry_counts` (162) — те, що рахується з уже прочитаних відміток.
  Разом ~11 запитів; експорт викликає `get_grid` двічі.
- **Стане:** прочитати уроки, стовпчики й відмітки один раз і передати в `_computed(journal, student_ids, lessons, columns, entries)`; ~6 запитів.
- **Виграш:** удвічі менше запитів при відкритті журналу, зміні семестру, кожному `reload_grid` та експорті. **Ризик:** низький. **Обсяг:** S.

### A3. Кожне натискання клавіші вантажить відмітки всього класу
- **Де:** `journals_page.py:547-562` (`set_cell` + `student_computed`), `journal_service.py:511-513, 523`; `_info()` `487-489`.
- **Було:** щоб перерахувати рядок одного учня, читаються відмітки всіх учнів за рік (30 учнів × 100 уроків ≈ 3000 ORM-об'єктів),
  усі оцінки стовпчиків і підсумкові; `_info` читає всі уроки заради одного номера.
- **Стане:** `repo.entries(lesson_ids, student_id=None)` та фільтр за учнем у `extra_grades` / `final_grades`.
- **Виграш:** ~×30 менше рядків на кожне введення оцінки. **Ризик:** низький. **Обсяг:** S.

### A4. Модель таблиці шукає урок перебором на кожну клітинку
- **Де:** `journal_grid.py:179-183` (`lesson_at`), викликається з `cell()` `199-203` — тобто з `data()` для `CellRole`, `DisplayRole`, `ToolTipRole`.
- **Стане:** `self.cells.get((student_id, self.columns[column].id), EMPTY_CELL)` — id уроку вже є в `GridColumn`; для заголовків — словник `lessons_by_id` у `set_grid`.
- **Виграш:** малювання клітинки O(1) замість O(уроків); помітно при прокручуванні повного семестру. **Ризик:** низький. **Обсяг:** S.

### A5. Список усіх журналів чи класів заради одного
- **Де:** `journals_page.py:425-426` (`open_journal`: `list_journals(всі)` лише заради меж семестрів, далі одразу `get_grid`, який повертає той самий
  `JournalInfo`), `735-738` (`_on_delete_journal`), `classes_page.py:393-398` (`_load_detail`). `journal_repository.py:43-51` — `school_class` і `subject`
  довантажуються окремим запитом на журнал.
- **Стане:** `get_journal(teacher_id, journal_id)` / `ClassService.get_class()`; у запиті списку — `joinedload(Journal.school_class), joinedload(Journal.subject)`.
- **Виграш:** −2…N запитів на відкриття журналу чи класу. **Ризик:** низький–середній (додається метод у `JournalApi` і фейк). **Обсяг:** S.

### A6. Міграції запускаються при кожному старті встановленої версії
- **Де:** `embedded_db.py:557-577`: `backup_before_migration` уже знає `current_revision` і `script_head`, але `upgrade_schema` викликається завжди.
- **Стане:** якщо ревізія дорівнює head — Alembic не імпортувати й не запускати.
- **Виграш:** не заміряно (потрібна зібрана версія); орієнтовно кількасот мс на старті. **Ризик:** середній (шлях оновлення, перевіряти `--smoke`). **Обсяг:** S.

---

## Мертвий код

### D1. Залишки режиму «лише читання»
- **Де:** `JournalGridModel.read_only` — `journal_grid.py:151, 164, 218, 736, 741` (завжди `False`); `LessonPanel._read_only` і параметр `read_only` —
  `lesson_panel.py:163, 222, 228, 290, 350, 409, 419`; `journals_page.py:463` (передає `False`), `468-469` (`setVisible(True)`, `setEnabled(True)` щоразу);
  `_own_lesson(editable=...)` — `journal_service.py:466-471` (ніхто не передає `True`).
- **Виграш:** ~−25 рядків і менше хибних розгалужень. **Ризик:** низький (поправити виклики в `tests/ui/test_lesson_panel.py`). **Обсяг:** S.

### D2. Те, що ніхто не викликає
- `MainWindow._empty_state` — `main_window.py:182-213` (32 рядки, кнопка «з'явиться на наступному етапі»).
- `DeleteLessonDialog` — `journal_dialogs.py:381-392`: урок з відмітками більше не видаляється; клас лишився тільки в тестах і `scripts/qa/screens.py`.
- `JournalRepository.lessons` — `journal_repository.py:111-118`; `BackupService.tools_available` — `backup_service.py:239-240`.
- `StudentRole` — `journal_grid.py:52, 314-315`; `theme._settings` — `theme.py:226-227` (обгортка над `app_settings`).
- Лише для тестів: `semesters.next_school_year` (`semesters.py:100-102`, дубль `_add_years`), `class_service.parse_student_list` (`107-109`),
  `LessonPanel.set_lessons` (`lesson_panel.py:231-233`, «сумісність зі старою сторінкою»).
- Обгортки в один рядок: `ClassService.renumber` (`class_service.py:327-329`), `_cancel_editor` (`lesson_panel.py:379-380`),
  `_sync_panel` (`journals_page.py:514-516`), `open_class` (`classes_page.py:386-388`), `clear_error` (`class_dialogs.py:60-61`).
- `ClassRepository.journals_of_class` ≡ `JournalRepository.journals_of_class` (`class_repository.py:37`, `journal_repository.py:28`); `rotate()` повертає список, який не читають.
- **Виграш:** ~−80 рядків (+ ~40 рядків тестів мертвого коду). **Ризик:** низький. **Обсяг:** S.

### D3. Запасні гілки «щоб старий код і фейки не ламалися»
- **Де:** значення за замовчуванням у DTO — `journal_types.py:75, 97-98, 180-183`; через них: `lesson.number or …` (`journal_grid.py:301`,
  `journals_page.py:597`, `lesson_panel.py:247-251`), `list(grid.columns) or [...]` (`journal_grid.py:158`), гілка порядку за датою в `merge_rows`
  з `_KIND_ORDER` (`lesson_panel.py:49, 81-88`).
- **Стане:** поля обов'язкові, сервіс їх завжди заповнює; запасні гілки зникають.
- **Виграш:** ~−30 рядків. **Ризик:** середній (тести створюють `LessonInfo` без `number`). **Обсяг:** S–M.

### D4. `scripts/qa/screens.py` (923 рядки)
- **Було:** разовий інструмент знімків екрана; повторює каркас e2e (підміна `session_scope`, модальних вікон, будівники даних) та імпортує мертвий `DeleteLessonDialog`.
- **Стане:** якщо знімки ще потрібні — спільні помічники з `tests/e2e/conftest.py`; якщо ні — видалити. Потрібне рішення автора.
- **Ризик:** низький. **Обсяг:** S (видалити) / M (спільний каркас).

---

## Порядок, який я б радив
1. T1 (3 рядки, −21 хв на кожен прогін) — далі все перевіряється швидко.
2. D1, D2, A1 — видалення й один відкладений імпорт, без зміни поведінки.
3. S3, S6, S7, S8, S11, A2–A4 — малі локальні правки.
4. S1, S2, S4, S5, R1, R2 — спільні віджети UI; найбільше мінус рядків, але найбільше дотичних тестів.
5. S13, D3, D4, A6 — після рішення автора.

## Рішення автора (15.11.2026)
- S13: дешевий варіант (фейк викликає справжні grade_calc і функції порядку).
- D4: `scripts/qa/screens.py` лишити, але спростити через спільні помічники e2e.
- D3, A6: вирішує Fable — робимо (A6 з перевіркою `--smoke`).
- Порядок: PR 1 — T1 + D1 + D2 + A1; PR 2 — S3, S6–S8, S11, A2–A4; PR 3 — S1, S2, S4, S5, R1, R2; PR 4 — S13 (дешево), D3, D4, A6, решта R.
