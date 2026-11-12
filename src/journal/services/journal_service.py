"""Журнали, уроки та клітинки таблиці оцінок (етап 5, специфікація docs/specs/stage-5.md).

Кожен метод перевіряє, що журнал/урок належить викладачу teacher_id (через classes.teacher_id);
чужий чи неіснуючий об'єкт дає JournalNotFound / LessonNotFound — наявність не розкривається.
"""
from datetime import date

from sqlalchemy.orm import Session

from journal.models import Attendance, Journal, Lesson, LessonEntry, LessonType
from journal.repositories.journal_repository import JournalRepository, boundaries_of, set_boundaries
from journal.services.class_service import StudentInfo
from journal.services.journal_types import (
    MAX_COMMENT,
    MAX_TOPIC,
    AttendanceCode,
    CellInfo,
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

ARCHIVED_WRITE = "Клас в архіві — журнал лише для перегляду"


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
        видаляються підсумкові оцінки, уроки (з їхніми відмітками) і сам журнал.
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
        Це єдиний запис, дозволений в журналі архівного класу.
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
        lessons = self.repo.lessons(journal_id, semester)
        lesson_ids = [lesson.id for lesson in lessons]
        counts = self.repo.entry_counts(lesson_ids)

        # Активні учні за номером, потім вибулі, у яких є відмітки в цьому журналі (за алфавітом).
        with_entries = self.repo.student_ids_with_entries(journal_id)
        students = self.repo.students(journal.class_id)
        active = sorted((s for s in students if not s.archived), key=lambda s: (s.position, s.id))
        archived = sorted(
            (s for s in students if s.archived and s.id in with_entries),
            key=lambda s: (ukrainian_sort_key(s.full_name), s.id),
        )
        cells = {(e.student_id, e.lesson_id): _cell_info(e) for e in self.repo.entries(lesson_ids)}
        total = self.repo.lesson_counts([journal_id]).get(journal_id, 0)
        return GridData(
            journal=_journal_info(journal, total),
            semester=semester,
            students=[StudentInfo(s.id, s.full_name, s.position, s.archived) for s in active + archived],
            lessons=[_lesson_info(lesson, counts.get(lesson.id, 0)) for lesson in lessons],
            cells=cells,
        )

    # --- уроки ---

    def create_lesson(
        self,
        teacher_id: int,
        journal_id: int,
        lesson_date: date,
        lesson_type: LessonTypeCode = "regular",
        topic: str | None = None,
    ) -> LessonInfo:
        journal = self._own_journal(teacher_id, journal_id, editable=True)
        semester = _check_date(journal, lesson_date)
        lesson = Lesson(
            journal_id=journal_id,
            lesson_date=lesson_date,
            semester=semester,
            lesson_type=_lesson_type(lesson_type),
            topic=_clean_topic(topic),
        )
        self.repo.add(lesson)
        return _lesson_info(lesson, 0)

    def update_lesson(
        self,
        teacher_id: int,
        lesson_id: int,
        lesson_date: date,
        lesson_type: LessonTypeCode,
        topic: str | None,
    ) -> LessonInfo:
        lesson = self._own_lesson(teacher_id, lesson_id, editable=True)
        semester = _check_date(lesson.journal, lesson_date)
        new_type = _lesson_type(lesson_type)
        new_topic = _clean_topic(topic)
        lesson.lesson_date = lesson_date
        lesson.semester = semester
        lesson.lesson_type = new_type
        lesson.topic = new_topic
        self.repo.session.flush()
        return _lesson_info(lesson, self.repo.entry_count(lesson_id))

    def delete_lesson(self, teacher_id: int, lesson_id: int) -> None:
        lesson = self._own_lesson(teacher_id, lesson_id, editable=True)
        self.repo.delete(lesson)  # клітинки зникають каскадом (FK lesson_id → CASCADE)

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
        lesson = self._own_lesson(teacher_id, lesson_id, editable=True)
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


def _lesson_info(lesson: Lesson, entry_count: int) -> LessonInfo:
    return LessonInfo(
        lesson.id, lesson.lesson_date, lesson.semester, lesson.lesson_type.value, lesson.topic, entry_count
    )


def _cell_info(e: LessonEntry) -> CellInfo:
    return CellInfo(e.attendance.value, e.grade, e.comment)
