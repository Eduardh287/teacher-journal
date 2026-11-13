"""Журнали, уроки та клітинки таблиці оцінок (етап 5, специфікація docs/specs/stage-5.md;
етап 6 — тематичні/семестрові/річні оцінки, д/з, нумерація, docs/specs/stage-6.md).

Кожен метод перевіряє, що журнал/урок належить викладачу teacher_id (через classes.teacher_id);
чужий чи неіснуючий об'єкт дає JournalNotFound / LessonNotFound — наявність не розкривається.
"""
from collections.abc import Callable
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
# Порядок стовпчиків з однаковою after_date: уроки → «Зошит» → «Тематична».
_RANK = {"lesson": 0, "notebook": 1, "thematic": 2}
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
        all_lessons = self.repo.all_lessons(journal_id)
        numbers = _numbers(all_lessons)
        lessons = [lesson for lesson in all_lessons if lesson.semester == semester]
        lesson_ids = [lesson.id for lesson in lessons]
        counts = self.repo.entry_counts(lesson_ids)

        # Активні учні за номером, потім вибулі, у яких є дані в цьому журналі (за алфавітом).
        with_entries = self.repo.student_ids_with_entries(journal_id)
        students = self.repo.students(journal.class_id)
        active = sorted((s for s in students if not s.archived), key=lambda s: (s.position, s.id))
        archived = sorted(
            (s for s in students if s.archived and s.id in with_entries),
            key=lambda s: (ukrainian_sort_key(s.full_name), s.id),
        )
        shown = active + archived
        cells = {(e.student_id, e.lesson_id): _cell_info(e) for e in self.repo.entries(lesson_ids)}
        total = self.repo.lesson_counts([journal_id]).get(journal_id, 0)

        columns = self.repo.extra_columns(journal_id)
        infos = _column_infos(columns, self.repo.extra_grade_counts(journal_id))
        mine = [c for c in columns if c.semester == semester]
        ordered = sorted(
            [(x.lesson_date, _RANK["lesson"], x.id, GridColumn("lesson", x.id)) for x in lessons]
            + [(c.after_date, _RANK[c.kind.value], c.id, GridColumn(c.kind.value, c.id)) for c in mine],
            key=lambda item: item[:3],
        )
        grid_columns = [item[3] for item in ordered] + [GridColumn("semester", None)]
        shown_keys = {("semester", semester)} | {(c.kind.value, c.id) for c in mine}
        if semester == 2:
            grid_columns.append(GridColumn("annual", None))
            shown_keys.add(("annual", 0))
        computed = {
            (sid, key): cell
            for (sid, key), cell in self._computed(journal, [st.id for st in shown]).items()
            if key in shown_keys
        }
        return GridData(
            journal=_journal_info(journal, total),
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
        semester = _check_date(journal, lesson_date)
        lesson = Lesson(
            journal_id=journal_id,
            lesson_date=lesson_date,
            semester=semester,
            lesson_type=_lesson_type(lesson_type),
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
        semester = _check_date(lesson.journal, lesson_date)
        new_type = _lesson_type(lesson_type)
        new_topic = _clean_topic(topic)
        new_homework = _clean_homework(homework)
        lesson.lesson_date = lesson_date
        lesson.semester = semester
        lesson.lesson_type = new_type
        lesson.topic = new_topic
        lesson.homework = new_homework
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
            withdrawn = self.repo.withdrawn_with_entries(lesson_id)
            if withdrawn:  # рядок вибулого лише для перегляду — пояснюємо, як усе ж очистити
                message += _WITHDRAWN_HINT.format(names=", ".join(withdrawn))
            raise JournalError(message)
        self.repo.delete(lesson)

    # --- стовпчики без дати ---

    def create_column(
        self, teacher_id: int, journal_id: int, kind: str, after_lesson_id: int
    ) -> ExtraColumnInfo:
        """Додає «Тематичну» / «Зошит» після уроку; дату користувач не задає."""
        journal = self._own_journal(teacher_id, journal_id)
        column_kind = _column_kind(kind)
        anchor = self._anchor(journal, after_lesson_id)
        if self.repo.find_extra_column(journal.id, column_kind, anchor.lesson_date) is not None:
            raise JournalError(COLUMN_EXISTS)
        column = ExtraColumn(
            journal_id=journal.id, kind=column_kind, semester=anchor.semester, after_date=anchor.lesson_date
        )
        self.repo.add(column)
        return self._column_info(column)

    def move_column(self, teacher_id: int, column_id: int, after_lesson_id: int) -> ExtraColumnInfo:
        """Переносить стовпчик після іншого уроку (семестр береться з уроку-якоря)."""
        column = self._own_column(teacher_id, column_id)
        anchor = self._anchor(column.journal, after_lesson_id)
        other = self.repo.find_extra_column(column.journal_id, column.kind, anchor.lesson_date)
        if other is not None and other.id != column.id:
            raise JournalError(COLUMN_EXISTS)
        column.after_date = anchor.lesson_date
        column.semester = anchor.semester
        self.repo.session.flush()
        return self._column_info(column)

    def delete_column(self, teacher_id: int, column_id: int) -> None:
        """«Зошит» з оцінками не видаляється; тематична — так (ручні оцінки зникають)."""
        column = self._own_column(teacher_id, column_id)
        count = self.repo.extra_grade_counts(column.journal_id).get(column.id, 0)
        if column.kind is ExtraColumnKind.NOTEBOOK and count:
            message = f"У стовпчику «Зошит» є оцінки ({count}) — його не можна видалити. Спершу очистьте їх."
            withdrawn = self.repo.withdrawn_with_extra_grades(column.id)
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
        student = self.repo.get_student(student_id)
        if student is None or student.class_id != journal.class_id:
            raise JournalError("Учня не знайдено")
        if student.archived:
            raise JournalError("Учень вибув — його клітинки лише для перегляду")
        if grade is not None and (
            isinstance(grade, bool) or not isinstance(grade, int) or not 1 <= grade <= 12
        ):
            raise JournalError("Оцінка має бути від 1 до 12")
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
        student = self.repo.get_student(student_id)
        if student is None or student.class_id != journal.class_id:
            raise JournalError("Учня не знайдено")
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
        student = self.repo.get_student(student_id)
        if student is None or student.class_id != lesson.journal.class_id:
            raise JournalError("Учня не знайдено")
        if student.archived:
            raise JournalError("Учень вибув — його клітинки лише для перегляду")
        if attendance not in ("present", "absent", "sick", "late"):
            raise JournalError("Невідомий вид відвідування")
        if grade is not None:
            if isinstance(grade, bool) or not isinstance(grade, int) or not 1 <= grade <= 12:
                raise JournalError("Оцінка має бути від 1 до 12")
            if attendance in ("absent", "sick"):
                raise JournalError("Відсутньому учню не можна поставити оцінку")
        comment = _clean_comment(comment)

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

    def _own_lesson(self, teacher_id: int, lesson_id: int, editable: bool = False) -> Lesson:
        lesson = self.repo.get_lesson(lesson_id)
        if lesson is None or lesson.journal.school_class.teacher_id != teacher_id:
            raise LessonNotFound("Урок не знайдено")
        if editable and lesson.journal.school_class.archived:
            raise JournalError(ARCHIVED_WRITE)
        return lesson

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
            self.repo.extra_columns(column.journal_id), self.repo.extra_grade_counts(column.journal_id)
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

    def _student_cells(self, journal: Journal, student_id: int) -> dict[ComputedKey, ComputedCell]:
        computed = self._computed(journal, [student_id])
        return {key: cell for (sid, key), cell in computed.items() if sid == student_id}

    def _computed(
        self, journal: Journal, student_ids: list[int]
    ) -> dict[tuple[int, ComputedKey], ComputedCell]:
        """Обчислювані клітинки (тематичні, зошит, семестрові, річна) для учнів — за один прохід."""
        wanted = set(student_ids)
        lessons = self.repo.all_lessons(journal.id)
        semester_of = {lesson.id: lesson.semester for lesson in lessons}
        date_of = {lesson.id: lesson.lesson_date for lesson in lessons}
        # Оцінки уроків учня: (дата, семестр, оцінка). Лише рядки з оцінкою: н/хв/з і коментарі не рахуються.
        grades: dict[int, list[tuple[date, int, int]]] = {sid: [] for sid in wanted}
        for entry in self.repo.entries(list(semester_of)):
            if entry.grade is not None and entry.student_id in wanted:
                grades[entry.student_id].append(
                    (date_of[entry.lesson_id], semester_of[entry.lesson_id], entry.grade)
                )
        columns = self.repo.extra_columns(journal.id)
        extra = {(g.column_id, g.student_id): g for g in self.repo.extra_grades(journal.id)}
        finals = {(f.student_id, f.kind): f for f in self.repo.final_grades(journal.id)}
        thematics = {
            sem: [c for c in columns if c.kind is ExtraColumnKind.THEMATIC and c.semester == sem]
            for sem in (1, 2)
        }

        result: dict[tuple[int, ComputedKey], ComputedCell] = {}
        for sid in wanted:
            effective: dict[int, int | None] = {}
            for sem in (1, 2):
                values: list[int | None] = []
                previous: date | None = None
                for column in thematics[sem]:
                    period = [
                        g for d, s, g in grades[sid]
                        if s == sem and (previous is None or d > previous) and d <= column.after_date
                    ]
                    cell = _cell(grade_calc.thematic(period), extra.get((column.id, sid)))
                    result[(sid, ("thematic", column.id))] = cell
                    values.append(cell.value)
                    previous = column.after_date
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


def _column_infos(columns: list[ExtraColumn], counts: dict[int, int]) -> list[ExtraColumnInfo]:
    """ExtraColumnInfo з порядковим номером виду в семестрі (за after_date, id)."""
    ordinals: dict[tuple[int, str], int] = {}
    infos = []
    for column in sorted(columns, key=lambda c: (c.after_date, c.id)):
        group = (column.semester, column.kind.value)
        ordinals[group] = ordinals.get(group, 0) + 1
        infos.append(
            ExtraColumnInfo(
                column.id, column.kind.value, column.semester, column.after_date,
                ordinals[group], counts.get(column.id, 0),
            )
        )
    return infos


def _column_kind(code: str) -> ExtraColumnKind:
    try:
        return ExtraColumnKind(code)
    except ValueError:
        raise JournalError("Невідомий вид стовпчика") from None


def _check_date(journal: Journal, lesson_date: date) -> int:
    """Семестр за датою й межами журналу; дата має лежати в навчальному році класу."""
    boundaries = boundaries_of(journal)
    semester = semester_for_date(lesson_date, boundaries)  # канікули → JournalError
    year = journal.school_class.school_year
    if not boundaries.contains(year, lesson_date):
        raise JournalError(f"Дата не належить навчальному року {year}")
    return semester


def _lesson_type(code: str) -> LessonType:
    try:
        return LessonType(code)
    except ValueError:
        raise JournalError("Невідомий тип уроку") from None


def _clean_topic(topic: str | None) -> str | None:
    topic = (topic or "").strip()
    if len(topic) > MAX_TOPIC:
        raise JournalError(f"Тема — не довше {MAX_TOPIC} символів")
    return topic or None


def _clean_homework(homework: str | None) -> str | None:
    homework = (homework or "").strip()
    if len(homework) > MAX_HOMEWORK:
        raise JournalError(f"Домашнє завдання — не довше {MAX_HOMEWORK} символів")
    return homework or None


def _clean_comment(comment: str | None) -> str | None:
    comment = (comment or "").strip()
    if len(comment) > MAX_COMMENT:
        raise JournalError(f"Коментар — не довше {MAX_COMMENT} символів")
    return comment or None


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
