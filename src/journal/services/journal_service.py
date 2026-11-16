"""Журнали, уроки та клітинки таблиці оцінок (етап 5, специфікація docs/specs/stage-5.md;
етап 6 — тематичні/семестрові/річні оцінки, д/з, нумерація, docs/specs/stage-6.md).

Кожен метод перевіряє, що журнал/урок належить викладачу teacher_id (через classes.teacher_id);
чужий чи неіснуючий об'єкт дає JournalNotFound / LessonNotFound — наявність не розкривається.
"""
from collections import Counter
from collections.abc import Callable
from typing import NamedTuple
from datetime import date

from sqlalchemy.orm import Session

from journal.models import (
    Attendance,
    ExtraColumn,
    ExtraColumnKind,
    ExtraGrade,
    FinalGrade,
    FinalGradeKind,
    Journal,
    Lesson,
    LessonEntry,
    LessonType,
    Student,
)
from journal.repositories.journal_repository import JournalRepository
from journal.services import grade_calc
from journal.services.boundaries_rows import boundaries_of, set_boundaries
from journal.services.class_service import StudentInfo
from journal.services.journal_types import (
    MAX_COMMENT,
    MAX_HOMEWORK,
    MAX_TOPIC,
    AttendanceCode,
    CellInfo,
    ComputedCell,
    ComputedKey,
    ExtraColumnInfo,
    GridColumn,
    GridData,
    JournalCandidate,
    JournalError,
    JournalInfo,
    JournalNotFound,
    LessonInfo,
    LessonNotFound,
    LessonTypeCode,
    semester_for_date,
)
from journal.services.semesters import SemesterBoundaries, SemesterError
from journal.services.settings_service import apply_boundaries
from journal.services.ua_sort import class_name_key, ukrainian_sort_key

# Архівний журнал редагується (оцінки, відмітки, уроки) — рішення автора 12.11.2026.
# Заборонено лише видаляти журнал архівного класу та створювати нові журнали для нього.
ARCHIVED_WRITE = "Клас в архіві — журнал не можна видалити; спершу поверніть клас"
COLUMN_EXISTS = "Після цього уроку вже є такий стовпчик"
COLUMN_MOVE_BLOCKED = (
    "Не можна видалити урок: стовпчик «{kind}» з оцінками мав би стати після попереднього уроку, "
    "де вже є такий стовпчик. Спершу видаліть або перенесіть його."
)
_KIND_NAMES = {"thematic": "Тематична", "notebook": "Зошит"}
_FINAL_KINDS = {
    ("semester", 1): FinalGradeKind.SEMESTER_1,
    ("semester", 2): FinalGradeKind.SEMESTER_2,
    ("annual", 0): FinalGradeKind.ANNUAL,
}


# Оцінки вибулого учня очистити не можна (його рядок лише для перегляду) — підказуємо шлях (рецензія Fable).
_WITHDRAWN_HINT = (
    "\n\nЧастина позначок належить вибулим учням ({names}). Їхні рядки лише для перегляду: "
    "щоб очистити ці клітинки, спершу поверніть учня до списку класу (сторінка «Класи»), "
    "а після очищення знову позначте його вибулим."
)

class JournalService:
    def __init__(self, session: Session) -> None:
        self.repo = JournalRepository(session)

    # --- журнали ---

    def list_journals(self, teacher_id: int, include_archived: bool = False) -> list[JournalInfo]:
        journals = self.repo.journals_for_teacher(teacher_id, include_archived)
        counts = self.repo.lesson_counts([j.id for j in journals])
        journals.sort(
            key=lambda j: (class_name_key(j.school_class.name), ukrainian_sort_key(j.subject.name))
        )
        return [_journal_info(j, counts.get(j.id, 0)) for j in journals]

    def list_journal_candidates(self, teacher_id: int) -> list[JournalCandidate]:
        classes = self.repo.candidate_classes(teacher_id)
        taken = self.repo.existing_pairs([c.id for c in classes])
        classes.sort(key=lambda c: (class_name_key(c.name), c.school_year))
        subjects = sorted(self.repo.subjects(), key=lambda s: ukrainian_sort_key(s.name))
        return [
            JournalCandidate(c.id, c.name, c.school_year, s.id, s.name)
            for c in classes
            for s in subjects
            if (c.id, s.id) not in taken
        ]

    def create_journal(self, teacher_id: int, class_id: int, subject_id: int) -> JournalInfo:
        school_class = self.repo.get_class(class_id)
        if school_class is None or school_class.teacher_id != teacher_id:
            raise JournalError("Клас не знайдено")
        if school_class.archived:
            raise JournalError("Клас в архіві — спершу поверніть його")
        if self.repo.get_subject(subject_id) is None:
            raise JournalError("Предмет не знайдено")
        if self.repo.journal_exists(class_id, subject_id):
            raise JournalError("Такий журнал уже існує")
        journal = Journal(class_id=class_id, subject_id=subject_id)
        teacher = self.repo.get_teacher(teacher_id)
        if teacher is not None:
            set_boundaries(journal, boundaries_of(teacher))  # знімок глобальних меж
        self.repo.add(journal)
        return _journal_info(journal, 0)

    def delete_journal(self, teacher_id: int, journal_id: int, with_contents: bool = False) -> None:
        """Видаляє журнал.

        Порожній журнал видаляється одразу. Журнал з уроками чи оцінками — лише з явним
        with_contents=True (рішення автора після показу викладачці): тоді в одній транзакції
        видаляються підсумкові оцінки, extra-стовпчики, уроки (з їхніми відмітками) і сам журнал.
        Без прапорця сервіс відмовляє — помилка в інтерфейсі не зітре оцінки.
        """
        journal = self._own_journal(teacher_id, journal_id, editable=True)
        if self.repo.has_lessons_or_finals(journal_id):
            if not with_contents:
                raise JournalError("У журналі є уроки чи оцінки — його не можна видалити")
            self.repo.delete_journal_contents(journal_id)
        self.repo.delete(journal)

    def set_journal_semesters(
        self, teacher_id: int, journal_id: int, boundaries: SemesterBoundaries
    ) -> JournalInfo:
        """Межі семестрів окремого журналу — лише для архівного класу.

        Журнали в роботі беруть межі з Налаштувань. Конфлікт з уроками → SemesterConflict.
        Журнали архівного класу загалом редагуються (рішення автора 12.11.2026); заборонено лише їх видалення.
        """
        journal = self._own_journal(teacher_id, journal_id)
        if not journal.school_class.archived:
            raise JournalError("Межі семестрів журналу в роботі змінюються в Налаштуваннях")
        try:
            boundaries.validate()
        except SemesterError as error:
            raise JournalError(str(error)) from None
        apply_boundaries(self.repo, [journal], boundaries)
        count = self.repo.lesson_counts([journal_id]).get(journal_id, 0)
        return _journal_info(journal, count)

    # --- таблиця ---

    def get_grid(self, teacher_id: int, journal_id: int, semester: int) -> GridData:
        journal = self._own_journal(teacher_id, journal_id)
        if semester not in (1, 2):
            raise JournalError("Семестр має бути 1 або 2")
        rows = self._rows(journal)
        all_lessons = rows.lessons
        numbers = _numbers(all_lessons)
        lessons = [lesson for lesson in all_lessons if lesson.semester == semester]
        lesson_ids = {lesson.id for lesson in lessons}
        counts = Counter(e.lesson_id for e in rows.entries)

        # Активні учні за номером, потім вибулі, у яких є дані в цьому журналі (за алфавітом):
        # клітинка, оцінка extra-стовпчика чи ручна підсумкова.
        with_entries = (
            {e.student_id for e in rows.entries}
            | {g.student_id for g in rows.extra_grades}
            | {f.student_id for f in rows.finals}
        )
        students = self.repo.students(journal.class_id)
        active = sorted((s for s in students if not s.archived), key=lambda s: (s.position, s.id))
        archived = sorted(
            (s for s in students if s.archived and s.id in with_entries),
            key=lambda s: (ukrainian_sort_key(s.full_name), s.id),
        )
        shown = active + archived
        cells = {(e.student_id, e.lesson_id): _cell_info(e) for e in rows.entries if e.lesson_id in lesson_ids}

        infos = _column_infos(rows.columns, Counter(g.column_id for g in rows.extra_grades), all_lessons)
        mine = [c for c in rows.columns if c.semester == semester]
        ordered = _display_order(all_lessons, lessons, mine)
        grid_columns = [GridColumn(kind, item.id) for kind, item in ordered] + [GridColumn("semester", None)]
        shown_keys = {("semester", semester)} | {(c.kind.value, c.id) for c in mine}
        if semester == 2:
            grid_columns.append(GridColumn("annual", None))
            shown_keys.add(("annual", 0))
        computed = {
            (sid, key): cell
            for (sid, key), cell in self._computed([st.id for st in shown], rows).items()
            if key in shown_keys
        }
        return GridData(
            journal=_journal_info(journal, len(all_lessons)),
            semester=semester,
            students=[StudentInfo(s.id, s.full_name, s.position, s.archived) for s in shown],
            lessons=[
                _lesson_info(lesson, counts.get(lesson.id, 0), numbers[lesson.id]) for lesson in lessons
            ],
            cells=cells,
            columns=grid_columns,
            extra_columns=[info for info in infos if info.semester == semester],
            computed=computed,
        )

    # --- уроки ---

    def create_lesson(
        self,
        teacher_id: int,
        journal_id: int,
        lesson_date: date,
        lesson_type: LessonTypeCode = "regular",
        topic: str | None = None,
        homework: str | None = None,
    ) -> LessonInfo:
        journal = self._own_journal(teacher_id, journal_id)
        semester = _check_date(boundaries_of(journal), journal.school_class.school_year, lesson_date)
        lesson = Lesson(
            journal_id=journal_id,
            lesson_date=lesson_date,
            semester=semester,
            lesson_type=_enum(LessonType, lesson_type, "Невідомий тип уроку"),
            topic=_clean_topic(topic),
            homework=_clean_homework(homework),
        )
        self.repo.add(lesson)
        return self._info(lesson, 0)

    def update_lesson(
        self,
        teacher_id: int,
        lesson_id: int,
        lesson_date: date,
        lesson_type: LessonTypeCode,
        topic: str | None,
        homework: str | None = None,
    ) -> LessonInfo:
        lesson = self._own_lesson(teacher_id, lesson_id)
        semester = _check_date(
            boundaries_of(lesson.journal), lesson.journal.school_class.school_year, lesson_date
        )
        new_type = _enum(LessonType, lesson_type, "Невідомий тип уроку")  # усю перевірку — до першого присвоєння
        topic, homework = _clean_topic(topic), _clean_homework(homework)
        lesson.lesson_date, lesson.semester, lesson.lesson_type = lesson_date, semester, new_type
        lesson.topic, lesson.homework = topic, homework
        # Стовпчики, прив'язані до цього уроку, їдуть разом з ним (дата й семестр якоря).
        for column in self.repo.columns_anchored_to(lesson.id):
            column.after_date = lesson_date
            column.semester = semester
        self.repo.session.flush()
        return self._info(lesson, self.repo.entry_count(lesson_id))

    def set_homework(self, teacher_id: int, lesson_id: int, homework: str | None) -> LessonInfo:
        """Швидке редагування д/з: trim, порожнє → None, понад 500 символів → помилка."""
        lesson = self._own_lesson(teacher_id, lesson_id)
        lesson.homework = _clean_homework(homework)
        self.repo.session.flush()
        return self._info(lesson, self.repo.entry_count(lesson_id))

    def delete_lesson(self, teacher_id: int, lesson_id: int) -> None:
        """Урок з будь-якою відміткою чи оцінкою не видаляється (рішення викладачки)."""
        lesson = self._own_lesson(teacher_id, lesson_id)
        count = self.repo.entry_count(lesson_id)
        if count:
            message = (
                f"Урок має оцінки чи позначки ({count}) — його не можна видалити. "
                "Спершу очистьте клітинки цього уроку."
            )
            withdrawn = self.repo.withdrawn_with(LessonEntry, LessonEntry.lesson_id, lesson_id)
            if withdrawn:  # рядок вибулого лише для перегляду — пояснюємо, як усе ж очистити
                message += _WITHDRAWN_HINT.format(names=", ".join(withdrawn))
            raise JournalError(message)
        self._reanchor_columns_of(lesson)
        self.repo.delete(lesson)

    def _reanchor_columns_of(self, lesson: Lesson) -> None:
        """Стовпчики, прив'язані до видаленого уроку, переходять до ПОПЕРЕДНЬОГО уроку журналу
        (за порядком таблиці), щоб не «стрибати»; якщо попереднього немає — лишаються без якоря
        на тій самій даті (after_date не змінюється), тобто на початку."""
        attached = self.repo.columns_anchored_to(lesson.id)
        if not attached:
            return
        ordered = self.repo.all_lessons(lesson.journal_id)
        index = next(i for i, x in enumerate(ordered) if x.id == lesson.id)
        previous = ordered[index - 1] if index else None
        # Лише попередній урок ТОГО САМОГО семестру: інакше стовпчик «переїхав» би в інший
        # семестр і тихо змінив семестрові оцінки (рецензія Fable, PR #16).
        if previous is not None and previous.semester != lesson.semester:
            previous = None
        counts = self.repo.extra_grade_counts(lesson.journal_id)
        duplicates = set()
        if previous is not None:
            for column in attached:
                if self.repo.find_extra_column(column.journal_id, column.kind, previous.id) is not None:
                    # Після попереднього уроку вже є стовпчик цього виду: порожній дублікат зникає.
                    if counts.get(column.id, 0):
                        raise JournalError(COLUMN_MOVE_BLOCKED.format(kind=_KIND_NAMES[column.kind.value]))
                    duplicates.add(column.id)
        for column in attached:
            if previous is None:
                column.after_lesson_id = None
                continue
            if column.id in duplicates:
                self.repo.session.delete(column)
                continue
            _attach(column, previous)
        self.repo.session.flush()

    # --- стовпчики без дати ---

    def create_column(
        self, teacher_id: int, journal_id: int, kind: str, after_lesson_id: int
    ) -> ExtraColumnInfo:
        """Додає «Тематичну» / «Зошит» після уроку; дату користувач не задає."""
        journal = self._own_journal(teacher_id, journal_id)
        column_kind = _enum(ExtraColumnKind, kind, "Невідомий вид стовпчика")
        anchor = self._anchor(journal, after_lesson_id)
        if self.repo.find_extra_column(journal.id, column_kind, anchor.id) is not None:
            raise JournalError(COLUMN_EXISTS)
        column = ExtraColumn(journal_id=journal.id, kind=column_kind)
        _attach(column, anchor)
        self.repo.add(column)
        return self._column_info(column)

    def move_column(self, teacher_id: int, column_id: int, after_lesson_id: int) -> ExtraColumnInfo:
        """Переносить стовпчик після іншого уроку (семестр береться з уроку-якоря)."""
        column = self._own_column(teacher_id, column_id)
        anchor = self._anchor(column.journal, after_lesson_id)
        other = self.repo.find_extra_column(column.journal_id, column.kind, anchor.id)
        if other is not None and other.id != column.id:
            raise JournalError(COLUMN_EXISTS)
        _attach(column, anchor)
        self.repo.session.flush()
        return self._column_info(column)

    def delete_column(self, teacher_id: int, column_id: int) -> None:
        """«Зошит» з оцінками не видаляється; тематична — так (ручні оцінки зникають)."""
        column = self._own_column(teacher_id, column_id)
        count = self.repo.extra_grade_counts(column.journal_id).get(column.id, 0)
        if column.kind is ExtraColumnKind.NOTEBOOK and count:
            message = f"У стовпчику «Зошит» є оцінки ({count}) — його не можна видалити. Спершу очистьте їх."
            withdrawn = self.repo.withdrawn_with(ExtraGrade, ExtraGrade.column_id, column.id)
            if withdrawn:
                message += _WITHDRAWN_HINT.format(names=", ".join(withdrawn))
            raise JournalError(message)
        self.repo.delete(column)  # оцінки стовпчика видаляє каскад

    # --- обчислювані клітинки ---

    def set_override(
        self,
        teacher_id: int,
        journal_id: int,
        student_id: int,
        key: ComputedKey,
        grade: int | None,
        na: bool = False,
    ) -> dict[ComputedKey, ComputedCell]:
        """Ручна оцінка (або «н/а») в обчислюваній клітинці чи оцінка «Зошита».

        grade=None і na=False — прибрати ручне значення (повернути автоматичне)."""
        journal = self._own_journal(teacher_id, journal_id)
        self._own_student(journal.class_id, student_id, editable=True)
        _check_grade(grade)
        if grade is not None and na:
            raise JournalError("Вкажіть або оцінку, або «н/а»")
        kind, ident = key
        if kind in ("thematic", "notebook"):
            column = self.repo.get_extra_column(ident)
            if column is None or column.journal_id != journal.id or column.kind.value != kind:
                raise JournalError("Стовпчик не знайдено")
            if kind == "notebook" and na:
                raise JournalError("Для «Зошита» «н/а» не передбачено")
            self._store(
                self.repo.get_extra_grade(column.id, student_id),
                lambda: ExtraGrade(column_id=column.id, student_id=student_id),
                grade,
                na,
            )
        elif key in _FINAL_KINDS:
            self._store(
                self.repo.get_final_grade(journal.id, student_id, _FINAL_KINDS[key]),
                lambda: FinalGrade(journal_id=journal.id, student_id=student_id, kind=_FINAL_KINDS[key]),
                grade,
                na,
            )
        else:
            raise JournalError("Невідомий стовпчик")
        self.repo.session.flush()
        return self._student_cells(journal, student_id)

    def student_computed(
        self, teacher_id: int, journal_id: int, student_id: int
    ) -> dict[ComputedKey, ComputedCell]:
        """Усі обчислювані клітинки учня (UI оновлює рядок після кожного set_cell)."""
        journal = self._own_journal(teacher_id, journal_id)
        self._own_student(journal.class_id, student_id)
        return self._student_cells(journal, student_id)

    # --- клітинки ---

    def set_cell(
        self,
        teacher_id: int,
        lesson_id: int,
        student_id: int,
        attendance: AttendanceCode,
        grade: int | None,
        comment: str | None,
    ) -> CellInfo | None:
        """Повний стан клітинки. Порожній стан («присутній», без оцінки й коментаря) видаляє рядок."""
        lesson = self._own_lesson(teacher_id, lesson_id)
        self._own_student(lesson.journal.class_id, student_id, editable=True)
        if attendance not in ("present", "absent", "sick", "late"):
            raise JournalError("Невідомий вид відвідування")
        if grade is not None:
            _check_grade(grade)
            if attendance in ("absent", "sick"):
                raise JournalError("Відсутньому учню не можна поставити оцінку")
        comment = _clean(comment, MAX_COMMENT, "Коментар")

        entry = self.repo.get_entry(lesson_id, student_id)
        if attendance == "present" and grade is None and comment is None:
            if entry is not None:
                self.repo.delete(entry)
            return None
        if entry is None:
            entry = LessonEntry(lesson_id=lesson_id, student_id=student_id)
            self.repo.session.add(entry)
        entry.attendance = Attendance(attendance)
        entry.grade = grade
        entry.comment = comment
        self.repo.session.flush()
        return _cell_info(entry)

    # --- допоміжне ---

    def _own_journal(self, teacher_id: int, journal_id: int, editable: bool = False) -> Journal:
        journal = self.repo.get_journal(journal_id)
        if journal is None or journal.school_class.teacher_id != teacher_id:
            raise JournalNotFound("Журнал не знайдено")
        if editable and journal.school_class.archived:
            raise JournalError(ARCHIVED_WRITE)
        return journal

    def _own_lesson(self, teacher_id: int, lesson_id: int) -> Lesson:
        lesson = self.repo.get_lesson(lesson_id)
        if lesson is None or lesson.journal.school_class.teacher_id != teacher_id:
            raise LessonNotFound("Урок не знайдено")
        return lesson

    def _own_student(self, class_id: int, student_id: int, editable: bool = False) -> Student:
        student = self.repo.get_student(student_id)
        if student is None or student.class_id != class_id:
            raise JournalError("Учня не знайдено")
        if editable and student.archived:
            raise JournalError("Учень вибув — його клітинки лише для перегляду")
        return student

    def _own_column(self, teacher_id: int, column_id: int) -> ExtraColumn:
        column = self.repo.get_extra_column(column_id)
        if column is None or column.journal.school_class.teacher_id != teacher_id:
            raise JournalError("Стовпчик не знайдено")
        return column

    def _anchor(self, journal: Journal, lesson_id: int) -> Lesson:
        """Урок журналу, після якого стоїть стовпчик."""
        lesson = self.repo.get_lesson(lesson_id)
        if lesson is None or lesson.journal_id != journal.id:
            raise LessonNotFound("Урок не знайдено")
        return lesson

    def _info(self, lesson: Lesson, entry_count: int) -> LessonInfo:
        numbers = _numbers(self.repo.all_lessons(lesson.journal_id))
        return _lesson_info(lesson, entry_count, numbers[lesson.id])

    def _column_info(self, column: ExtraColumn) -> ExtraColumnInfo:
        infos = _column_infos(
            self.repo.extra_columns(column.journal_id),
            self.repo.extra_grade_counts(column.journal_id),
            self.repo.all_lessons(column.journal_id),
        )
        return next(info for info in infos if info.id == column.id)

    def _store(self, row, make: Callable, grade: int | None, na: bool) -> None:
        """Записує, замінює або (grade=None, na=False) видаляє ручне значення."""
        if grade is None and not na:
            if row is not None:
                self.repo.delete(row)
            return
        if row is None:
            row = make()
            self.repo.session.add(row)
        row.grade = grade
        row.is_na = na

    def _rows(self, journal: Journal, student_id: int | None = None) -> "_Rows":
        """Усе, з чого рахуються клітинки журналу, — по одному запиту; з student_id — лише дані одного учня."""
        lessons = self.repo.all_lessons(journal.id)
        return _Rows(
            lessons,
            self.repo.extra_columns(journal.id),
            self.repo.entries([lesson.id for lesson in lessons], student_id),
            self.repo.extra_grades(journal.id, student_id),
            self.repo.final_grades(journal.id, student_id),
        )

    def _student_cells(self, journal: Journal, student_id: int) -> dict[ComputedKey, ComputedCell]:
        computed = self._computed([student_id], self._rows(journal, student_id))
        return {key: cell for (sid, key), cell in computed.items() if sid == student_id}

    def _computed(self, student_ids: list[int], rows: "_Rows") -> dict[tuple[int, ComputedKey], ComputedCell]:
        """Обчислювані клітинки (тематичні, зошит, семестрові, річна) для учнів — за один прохід."""
        wanted = set(student_ids)
        lessons, columns = rows.lessons, rows.columns
        # Оцінки уроків учня: урок → оцінка. Лише рядки з оцінкою: н/хв/з і коментарі не рахуються.
        grades: dict[int, dict[int, int]] = {sid: {} for sid in wanted}
        for entry in rows.entries:
            if entry.grade is not None and entry.student_id in wanted:
                grades[entry.student_id][entry.lesson_id] = entry.grade
        extra = {(g.column_id, g.student_id): g for g in rows.extra_grades}
        finals = {(f.student_id, f.kind): f for f in rows.finals}
        # Порядок таблиці в кожному семестрі: тематична підсумовує всі оцінки уроків між попередньою
        # тематичною («Зошит» — не межа й не рахується) і собою — саме в цьому порядку.
        sequence = {
            sem: _display_order(
                lessons,
                [x for x in lessons if x.semester == sem],
                [c for c in columns if c.kind is ExtraColumnKind.THEMATIC and c.semester == sem],
            )
            for sem in (1, 2)
        }

        result: dict[tuple[int, ComputedKey], ComputedCell] = {}
        for sid in wanted:
            effective: dict[int, int | None] = {}
            for sem in (1, 2):
                values: list[int | None] = []
                period: list[int] = []
                for item_kind, item in sequence[sem]:
                    if item_kind == "lesson":
                        if item.id in grades[sid]:
                            period.append(grades[sid][item.id])
                        continue
                    cell = _cell(grade_calc.thematic(period), extra.get((item.id, sid)))
                    result[(sid, ("thematic", item.id))] = cell
                    values.append(cell.value)
                    period = []
                kind = FinalGradeKind.SEMESTER_1 if sem == 1 else FinalGradeKind.SEMESTER_2
                cell = _cell(grade_calc.semester(values), finals.get((sid, kind)))
                result[(sid, ("semester", sem))] = cell
                effective[sem] = cell.value
            result[(sid, ("annual", 0))] = _cell(
                grade_calc.annual(effective[1], effective[2]), finals.get((sid, FinalGradeKind.ANNUAL))
            )
            for column in columns:
                if column.kind is ExtraColumnKind.NOTEBOOK:
                    row = extra.get((column.id, sid))
                    result[(sid, ("notebook", column.id))] = ComputedCell(
                        None, False, 0, 0, row.grade if row else None, False
                    )
        return result


class _Rows(NamedTuple):
    lessons: list[Lesson]
    columns: list[ExtraColumn]
    entries: list[LessonEntry]
    extra_grades: list[ExtraGrade]
    finals: list[FinalGrade]


def _cell(calc: grade_calc.Calc, override) -> ComputedCell:
    """ComputedCell з автоматичного результату й ручного рядка (оцінка чи «н/а»)."""
    return ComputedCell(
        auto=calc.value,
        auto_na=calc.is_na,
        total=calc.total,
        count=calc.count,
        override=override.grade if override is not None else None,
        override_na=bool(override.is_na) if override is not None else False,
    )


def _numbers(lessons: list[Lesson]) -> dict[int, int]:
    """Наскрізні номери уроків за навчальний рік: порядок (дата, id), з 1."""
    ordered = sorted(lessons, key=lambda x: (x.lesson_date, x.id))
    return {lesson.id: number for number, lesson in enumerate(ordered, start=1)}


def _lesson_key(lesson: Lesson) -> tuple:
    return (lesson.lesson_date, lesson.id, 0, 0)


def _column_key(column: ExtraColumn, by_id: dict[int, Lesson]) -> tuple:
    """Ключ порядку: стовпчик стоїть одразу після уроку-якоря, а кілька стовпчиків після одного
    уроку — у порядку створення. Без якоря (NULL) — на дату after_date ПЕРЕД усіма її уроками
    (id уроків ≥ 1, тож 0 менший за будь-який)."""
    anchor = by_id.get(column.after_lesson_id) if column.after_lesson_id is not None else None
    if anchor is not None:
        return (anchor.lesson_date, anchor.id, 1, column.id)
    return (column.after_date, 0, 1, column.id)


def _display_order(
    all_lessons: list[Lesson], lessons: list[Lesson], columns: list[ExtraColumn]
) -> list[tuple[str, Lesson | ExtraColumn]]:
    """Уроки й стовпчики (kind, об'єкт) у порядку таблиці. all_lessons — для пошуку якорів."""
    by_id = {x.id: x for x in all_lessons}
    keyed = [(_lesson_key(x), "lesson", x) for x in lessons]
    keyed += [(_column_key(c, by_id), c.kind.value, c) for c in columns]
    keyed.sort(key=lambda item: item[0])
    return [(kind, item) for _, kind, item in keyed]


def _column_infos(
    columns: list[ExtraColumn], counts: dict[int, int], all_lessons: list[Lesson]
) -> list[ExtraColumnInfo]:
    """ExtraColumnInfo з порядковим номером виду в семестрі (у порядку таблиці)."""
    by_id = {x.id: x for x in all_lessons}
    ordinals: dict[tuple[int, str], int] = {}
    infos = []
    for column in sorted(columns, key=lambda c: _column_key(c, by_id)):
        group = (column.semester, column.kind.value)
        ordinals[group] = ordinals.get(group, 0) + 1
        infos.append(
            ExtraColumnInfo(
                column.id, column.kind.value, column.semester, column.after_date,
                ordinals[group], counts.get(column.id, 0),
            )
        )
    return infos


def _enum(cls, code: str, message: str):
    """Член перелічення за кодом або JournalError."""
    try:
        return cls(code)
    except ValueError:
        raise JournalError(message) from None


def _check_grade(grade: int | None) -> None:
    if grade is not None and (isinstance(grade, bool) or not isinstance(grade, int) or not 1 <= grade <= 12):
        raise JournalError("Оцінка має бути від 1 до 12")


def _attach(column: ExtraColumn, lesson: Lesson) -> None:
    """Прив'язує стовпчик до уроку-якоря: дата й семестр беруться з нього."""
    column.after_lesson_id = lesson.id
    column.after_date = lesson.lesson_date
    column.semester = lesson.semester


def _check_date(boundaries: SemesterBoundaries, year: str, lesson_date: date) -> int:
    """Семестр за датою й межами журналу; дата має лежати в навчальному році класу."""
    semester = semester_for_date(lesson_date, boundaries)  # канікули → JournalError
    if not boundaries.contains(year, lesson_date):
        raise JournalError(f"Дата не належить навчальному року {year}")
    return semester


def _clean(text: str | None, limit: int, label: str) -> str | None:
    """Обрізані пробіли; порожнє → None; понад limit символів → JournalError."""
    text = (text or "").strip()
    if len(text) > limit:
        raise JournalError(f"{label} — не довше {limit} символів")
    return text or None


def _clean_topic(topic: str | None) -> str | None:
    return _clean(topic, MAX_TOPIC, "Тема")


def _clean_homework(homework: str | None) -> str | None:
    return _clean(homework, MAX_HOMEWORK, "Домашнє завдання")


def _journal_info(j: Journal, lesson_count: int) -> JournalInfo:
    c = j.school_class
    return JournalInfo(
        j.id, c.id, c.name, c.school_year, j.subject_id, j.subject.name, c.archived, lesson_count,
        boundaries_of(j),
    )


def _lesson_info(lesson: Lesson, entry_count: int, number: int) -> LessonInfo:
    return LessonInfo(
        lesson.id, lesson.lesson_date, lesson.semester, lesson.lesson_type.value, lesson.topic,
        entry_count, lesson.homework, number,
    )


def _cell_info(e: LessonEntry) -> CellInfo:
    return CellInfo(e.attendance.value, e.grade, e.comment)
