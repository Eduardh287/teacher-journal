"""Фейковий сервіс журналів у пам'яті: реалізує JournalApi для тестів інтерфейсу (без БД)."""
from dataclasses import replace
from datetime import date

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
    LessonConflict,
    LessonInfo,
    LessonNotFound,
    LessonTypeCode,
    SemesterConflict,
    semester_for_date,
)
from journal.services.semesters import SemesterBoundaries

ARCHIVED_CLASS_TEXT = "Клас в архіві — журнал не можна видалити; спершу поверніть клас"


class FakeJournalService:
    """Один клас, один журнал (id=1) за замовчуванням. Усі виклики пишуться в `calls`."""

    def __init__(
        self,
        student_names: list[str] | None = None,
        *,
        archived_students: tuple[str, ...] = (),
        class_name: str = "9-А",
        subject_name: str = "Математика",
        school_year: str = "2025-2026",
        class_archived: bool = False,
    ) -> None:
        names = student_names if student_names is not None else ["Коваленко Олена", "Шевченко Іван"]
        self.students: list[StudentInfo] = [
            StudentInfo(id=i + 1, full_name=n, position=i + 1, archived=False) for i, n in enumerate(names)
        ]
        for n in archived_students:
            self.students.append(
                StudentInfo(id=len(self.students) + 1, full_name=n, position=len(self.students) + 1, archived=True)
            )
        self.journal = JournalInfo(
            id=1, class_id=1, class_name=class_name, school_year=school_year,
            subject_id=1, subject_name=subject_name, class_archived=class_archived, lesson_count=0,
        )
        self.journals: list[JournalInfo] = [self.journal]
        self.candidates: list[JournalCandidate] = []
        self.lessons: list[dict] = []
        self.cells: dict[tuple[int, int], CellInfo] = {}
        self.calls: list[tuple] = []
        self.fail_next: JournalError | None = None
        self._next_lesson_id = 1

    # --- службове ---

    def _enter(self, name: str, *args) -> None:
        self.calls.append((name, *args))
        if self.fail_next is not None:
            error, self.fail_next = self.fail_next, None
            raise error

    def calls_of(self, name: str) -> list[tuple]:
        return [c for c in self.calls if c[0] == name]

    def add_lesson(self, lesson_date: date, lesson_type: LessonTypeCode = "regular", topic: str | None = None) -> int:
        """Додає урок напряму (без запису в calls) і повертає його id."""
        lesson_id = self._next_lesson_id
        self._next_lesson_id += 1
        self.lessons.append({"id": lesson_id, "date": lesson_date, "type": lesson_type, "topic": topic})
        return lesson_id

    def put_cell(self, student_id: int, lesson_id: int, attendance="present", grade=None, comment=None) -> None:
        self.cells[(student_id, lesson_id)] = CellInfo(attendance, grade, comment)

    def _info(self, row: dict) -> LessonInfo:
        count = sum(1 for (_, lid) in self.cells if lid == row["id"])
        semester = semester_for_date(row["date"], self.journal.boundaries)
        return LessonInfo(row["id"], row["date"], semester, row["type"], row["topic"], count)

    def _lesson(self, lesson_id: int) -> dict:
        for row in self.lessons:
            if row["id"] == lesson_id:
                return row
        raise LessonNotFound("Урок не знайдено")

    def _check_writable(self) -> None:
        """Архівний журнал теж редагується (рішення автора 12.11.2026)."""

    # --- JournalApi ---

    def list_journals(self, teacher_id: int, include_archived: bool = False) -> list[JournalInfo]:
        self._enter("list_journals", include_archived)
        result = [replace(j, lesson_count=len(self.lessons)) for j in self.journals]
        return [j for j in result if include_archived or not j.class_archived]

    def list_journal_candidates(self, teacher_id: int) -> list[JournalCandidate]:
        self._enter("list_journal_candidates")
        return list(self.candidates)

    def create_journal(self, teacher_id: int, class_id: int, subject_id: int) -> JournalInfo:
        self._enter("create_journal", class_id, subject_id)
        match = next((c for c in self.candidates if (c.class_id, c.subject_id) == (class_id, subject_id)), None)
        if match is None:
            raise JournalError("Такий журнал уже існує")
        self.candidates.remove(match)
        info = JournalInfo(
            id=max((j.id for j in self.journals), default=0) + 1,
            class_id=class_id, class_name=match.class_name, school_year=match.school_year,
            subject_id=subject_id, subject_name=match.subject_name, class_archived=False, lesson_count=0,
        )
        self.journals.append(info)
        return info

    def delete_journal(self, teacher_id: int, journal_id: int, with_contents: bool = False) -> None:
        self._enter("delete_journal", journal_id, with_contents)
        if self.journal.class_archived:
            raise JournalError(ARCHIVED_CLASS_TEXT)
        if all(j.id != journal_id for j in self.journals):
            raise JournalNotFound("Журнал не знайдено")
        if self.lessons and not with_contents:
            raise JournalError("У журналі є уроки чи оцінки — його не можна видалити")
        self.lessons.clear()
        self.cells.clear()
        self.journals = [j for j in self.journals if j.id != journal_id]

    def set_journal_semesters(self, teacher_id: int, journal_id: int, boundaries: SemesterBoundaries) -> JournalInfo:
        self._enter("set_journal_semesters", journal_id, boundaries)
        if self.journal.id != journal_id:
            raise JournalNotFound("Журнал не знайдено")
        if not self.journal.class_archived:
            raise JournalError("Межі семестрів журналу в роботі змінюються в Налаштуваннях")
        boundaries.validate()
        conflicts = sorted(
            (
                LessonConflict(
                    self.journal.id, self.journal.class_name, self.journal.school_year,
                    self.journal.subject_name, row["date"],
                )
                for row in self.lessons
                if not boundaries.contains(self.journal.school_year, row["date"])
            ),
            key=lambda c: c.lesson_date,
        )
        if conflicts:
            raise SemesterConflict(conflicts)
        self.journal = replace(self.journal, boundaries=boundaries)
        self.journals = [self.journal if j.id == journal_id else j for j in self.journals]
        return self.journal

    def get_grid(self, teacher_id: int, journal_id: int, semester: int) -> GridData:
        self._enter("get_grid", journal_id, semester)
        if semester not in (1, 2):
            raise JournalError("Семестр має бути 1 або 2")
        if all(j.id != journal_id for j in self.journals):
            raise JournalNotFound("Журнал не знайдено")
        lessons = sorted((self._info(r) for r in self.lessons), key=lambda i: (i.lesson_date, i.id))
        lessons = [info for info in lessons if info.semester == semester]
        ids = {info.id for info in lessons}
        cells = {k: v for k, v in self.cells.items() if k[1] in ids}
        info = replace(self.journal, lesson_count=len(self.lessons))
        return GridData(info, semester, list(self.students), lessons, cells)

    def _check_date(self, lesson_date: date) -> None:
        boundaries = self.journal.boundaries
        semester_for_date(lesson_date, boundaries)
        if not boundaries.contains(self.journal.school_year, lesson_date):
            raise JournalError(f"Дата не належить навчальному року {self.journal.school_year}")

    @staticmethod
    def _topic(topic: str | None) -> str | None:
        topic = (topic or "").strip() or None
        if topic is not None and len(topic) > MAX_TOPIC:
            raise JournalError(f"Тема — не довше {MAX_TOPIC} символів")
        return topic

    def create_lesson(self, teacher_id, journal_id, lesson_date, lesson_type="regular", topic=None) -> LessonInfo:
        self._enter("create_lesson", journal_id, lesson_date, lesson_type, topic)
        self._check_writable()
        self._check_date(lesson_date)
        lesson_id = self.add_lesson(lesson_date, lesson_type, self._topic(topic))
        return self._info(self._lesson(lesson_id))

    def update_lesson(self, teacher_id, lesson_id, lesson_date, lesson_type, topic) -> LessonInfo:
        self._enter("update_lesson", lesson_id, lesson_date, lesson_type, topic)
        self._check_writable()
        row = self._lesson(lesson_id)
        self._check_date(lesson_date)
        row.update(date=lesson_date, type=lesson_type, topic=self._topic(topic))
        return self._info(row)

    def delete_lesson(self, teacher_id: int, lesson_id: int) -> None:
        self._enter("delete_lesson", lesson_id)
        self._check_writable()
        row = self._lesson(lesson_id)
        self.lessons.remove(row)
        self.cells = {k: v for k, v in self.cells.items() if k[1] != lesson_id}

    def set_cell(
        self,
        teacher_id: int,
        lesson_id: int,
        student_id: int,
        attendance: AttendanceCode,
        grade: int | None,
        comment: str | None,
    ) -> CellInfo | None:
        self._enter("set_cell", lesson_id, student_id, attendance, grade, comment)
        self._check_writable()
        self._lesson(lesson_id)
        student = next((s for s in self.students if s.id == student_id), None)
        if student is None:
            raise JournalError("Учня не знайдено")
        if student.archived:
            raise JournalError("Учень вибув — його клітинки лише для перегляду")
        if grade is not None and not 1 <= grade <= 12:
            raise JournalError("Оцінка має бути від 1 до 12")
        if grade is not None and attendance in ("absent", "sick"):
            raise JournalError("Відсутньому учню не можна поставити оцінку")
        comment = (comment or "").strip() or None
        if comment is not None and len(comment) > MAX_COMMENT:
            raise JournalError(f"Коментар — не довше {MAX_COMMENT} символів")
        key = (student_id, lesson_id)
        if attendance == "present" and grade is None and comment is None:
            self.cells.pop(key, None)
            return None
        cell = CellInfo(attendance, grade, comment)
        self.cells[key] = cell
        return cell
