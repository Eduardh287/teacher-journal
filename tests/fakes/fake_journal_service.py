"""Фейковий сервіс журналів у пам'яті: реалізує JournalApi для тестів інтерфейсу (без БД)."""
from dataclasses import replace
from datetime import date
from types import SimpleNamespace

from journal.services import grade_calc
from journal.services.class_service import StudentInfo
from journal.services.journal_service import (
    ARCHIVED_WRITE,
    COLUMN_EXISTS,
    _cell,
    _check_date,
    _check_grade,
    _clean,
    _clean_homework,
    _clean_topic,
    _column_key,
    _lesson_key,
    _numbers,
)
from journal.services.journal_types import (
    MAX_COMMENT,
    AttendanceCode,
    CellInfo,
    ComputedCell,
    ComputedKey,
    ExtraColumnInfo,
    ExtraColumnKind,
    GridColumn,
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
from journal.services.semesters import DEFAULT_BOUNDARIES, SemesterBoundaries


def _lesson_obj(row: dict) -> SimpleNamespace:
    """Рядок уроку фейка у вигляді, який розуміють функції порядку сервісу."""
    return SimpleNamespace(id=row["id"], lesson_date=row["date"])


def _column_obj(column: dict) -> SimpleNamespace:
    return SimpleNamespace(id=column["id"], after_lesson_id=column["after"], after_date=column["date"])


def _override(pair: tuple[int | None, bool] | None) -> SimpleNamespace | None:
    """Ручне значення (оцінка, н/а) у вигляді рядка БД для `_cell`; немає значення — None."""
    return None if pair is None else SimpleNamespace(grade=pair[0], is_na=pair[1])


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
            boundaries=DEFAULT_BOUNDARIES,
        )
        self.journals: list[JournalInfo] = [self.journal]
        self.candidates: list[JournalCandidate] = []
        self.lessons: list[dict] = []
        self.cells: dict[tuple[int, int], CellInfo] = {}
        self.calls: list[tuple] = []
        self.fail_next: JournalError | None = None
        self._next_lesson_id = 1
        # {"id", "kind", "date", "after": id уроку-якоря | None, "grades": {student_id: (grade|None, na)}}
        self.columns: list[dict] = []
        self._next_column_id = 1
        self.finals: dict[tuple[int, str, int], tuple[int | None, bool]] = {}  # (учень, "semester"/"annual", n)

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

    def add_column(self, kind: ExtraColumnKind, after_lesson_id: int) -> int:
        """Додає «Тем»/«Зош» після уроку напряму (без запису в calls) і повертає id."""
        column_id = self._next_column_id
        self._next_column_id += 1
        self.columns.append(
            {"id": column_id, "kind": kind, "date": self._lesson(after_lesson_id)["date"],
             "after": after_lesson_id, "grades": {}}
        )
        return column_id

    def put_extra_grade(self, column_id: int, student_id: int, grade: int | None, na: bool = False) -> None:
        """Ручна оцінка в тематичній / оцінка зошита напряму."""
        self._column(column_id)["grades"][student_id] = (grade, na)

    def put_final(self, student_id: int, kind: str, number: int, grade: int | None, na: bool = False) -> None:
        self.finals[(student_id, kind, number)] = (grade, na)

    def _column(self, column_id: int) -> dict:
        for col in self.columns:
            if col["id"] == column_id:
                return col
        raise JournalError("Стовпчик не знайдено")

    def _semester_of(self, d: date) -> int:
        return semester_for_date(d, self.journal.boundaries)

    def _col_key(self, column: dict) -> tuple:
        by_id = {row["id"]: _lesson_obj(row) for row in self.lessons}
        return _column_key(_column_obj(column), by_id)

    @staticmethod
    def _lesson_key(row: dict) -> tuple:
        return _lesson_key(_lesson_obj(row))

    def _extra_infos(self, semester: int) -> list[ExtraColumnInfo]:
        cols = sorted(
            (c for c in self.columns if self._semester_of(c["date"]) == semester), key=self._col_key
        )
        counts: dict[str, int] = {}
        result = []
        for c in cols:
            counts[c["kind"]] = counts.get(c["kind"], 0) + 1
            if c["kind"] == "notebook":
                grades = sum(1 for g, _ in c["grades"].values() if g is not None)
            else:
                grades = len(c["grades"])
            result.append(ExtraColumnInfo(c["id"], c["kind"], semester, c["date"], counts[c["kind"]], grades))
        return result

    # --- обчислення (ті самі grade_calc і `_cell`, що в сервісі) ---

    def _final(self, student_id: int, kind: str, number: int):
        return _override(self.finals.get((student_id, kind, number)))

    def _compute_semester(self, student_id: int, semester: int):
        thematics = [c for c in self.columns
                     if c["kind"] == "thematic" and self._semester_of(c["date"]) == semester]
        lessons = [r for r in self.lessons if self._semester_of(r["date"]) == semester]
        sequence = sorted(
            [(self._lesson_key(r), r, None) for r in lessons] + [(self._col_key(c), None, c) for c in thematics],
            key=lambda item: item[0],
        )
        result: dict[ComputedKey, ComputedCell] = {}
        values: list[int | None] = []
        period: list[int] = []
        for _, row, column in sequence:
            if row is not None:
                cell = self.cells.get((student_id, row["id"]))
                if cell is not None and cell.grade is not None:
                    period.append(cell.grade)
                continue
            cell = _cell(grade_calc.thematic(period), _override(column["grades"].get(student_id)))
            period = []
            result[("thematic", column["id"])] = cell
            values.append(cell.value)
        return result, _cell(grade_calc.semester(values), self._final(student_id, "semester", semester))

    def _computed_for(self, student_id: int, semester: int) -> dict[ComputedKey, ComputedCell]:
        result, sem_cell = self._compute_semester(student_id, semester)
        result[("semester", semester)] = sem_cell
        for column in self._extra_infos(semester):
            if column.kind == "notebook":
                grade, _ = self._column(column.id)["grades"].get(student_id, (None, False))
                if grade is not None:
                    result[("notebook", column.id)] = ComputedCell(None, False, 0, 0, grade, False)
        if semester == 2:
            sems = [self._compute_semester(student_id, n)[1] for n in (1, 2)]
            result[("annual", 0)] = _cell(
                grade_calc.annual(sems[0].value, sems[1].value), self._final(student_id, "annual", 0)
            )
            result[("semester", 1)] = sems[0]
        return result

    def student_computed(self, teacher_id, journal_id, student_id) -> dict[ComputedKey, ComputedCell]:
        self._enter("student_computed", journal_id, student_id)
        merged: dict[ComputedKey, ComputedCell] = {}
        for semester in (1, 2):
            merged.update(self._computed_for(student_id, semester))
        return merged

    def _info(self, row: dict) -> LessonInfo:
        count = sum(1 for (_, lid) in self.cells if lid == row["id"])
        semester = semester_for_date(row["date"], self.journal.boundaries)
        number = _numbers([_lesson_obj(r) for r in self.lessons])[row["id"]]
        return LessonInfo(
            row["id"], row["date"], semester, row["type"], row["topic"], count, row.get("homework"), number,
        )

    def _lesson(self, lesson_id: int) -> dict:
        for row in self.lessons:
            if row["id"] == lesson_id:
                return row
        raise LessonNotFound("Урок не знайдено")

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
            boundaries=DEFAULT_BOUNDARIES,
        )
        self.journals.append(info)
        return info

    def delete_journal(self, teacher_id: int, journal_id: int, with_contents: bool = False) -> None:
        self._enter("delete_journal", journal_id, with_contents)
        if self.journal.class_archived:
            raise JournalError(ARCHIVED_WRITE)
        if all(j.id != journal_id for j in self.journals):
            raise JournalNotFound("Журнал не знайдено")
        if self.lessons and not with_contents:
            raise JournalError("У журналі є уроки чи оцінки — його не можна видалити")
        self.lessons.clear()
        self.cells.clear()
        self.columns.clear()
        self.finals.clear()
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
        extras = self._extra_infos(semester)
        order = [((i.lesson_date, i.id, 0, 0), GridColumn("lesson", i.id)) for i in lessons]
        order += [(self._col_key(self._column(e.id)), GridColumn(e.kind, e.id)) for e in extras]
        columns = [col for _, col in sorted(order, key=lambda x: x[0])]
        columns.append(GridColumn("semester", None))
        if semester == 2:
            columns.append(GridColumn("annual", None))
        computed: dict[tuple[int, ComputedKey], ComputedCell] = {}
        for student in self.students:
            for key, cell in self._computed_for(student.id, semester).items():
                computed[(student.id, key)] = cell
        return GridData(
            info, semester, list(self.students), lessons, cells,
            columns=columns, extra_columns=extras, computed=computed,
        )

    def _check_date(self, lesson_date: date) -> None:
        _check_date(self.journal.boundaries, self.journal.school_year, lesson_date)

    def create_lesson(
        self, teacher_id, journal_id, lesson_date, lesson_type="regular", topic=None, homework=None
    ) -> LessonInfo:
        self._enter("create_lesson", journal_id, lesson_date, lesson_type, topic)
        self._check_date(lesson_date)
        lesson_id = self.add_lesson(lesson_date, lesson_type, _clean_topic(topic))
        self._lesson(lesson_id)["homework"] = _clean_homework(homework)
        return self._info(self._lesson(lesson_id))

    def update_lesson(
        self, teacher_id, lesson_id, lesson_date, lesson_type, topic, homework=None
    ) -> LessonInfo:
        self._enter("update_lesson", lesson_id, lesson_date, lesson_type, topic)
        row = self._lesson(lesson_id)
        self._check_date(lesson_date)
        row.update(date=lesson_date, type=lesson_type, topic=_clean_topic(topic),
                   homework=_clean_homework(homework))
        for column in self.columns:  # стовпчики-супутники їдуть разом з якорем
            if column["after"] == lesson_id:
                column["date"] = lesson_date
        return self._info(row)

    def set_homework(self, teacher_id, lesson_id, homework) -> LessonInfo:
        self._enter("set_homework", lesson_id, homework)
        row = self._lesson(lesson_id)
        row["homework"] = _clean_homework(homework)
        return self._info(row)

    def delete_lesson(self, teacher_id: int, lesson_id: int) -> None:
        self._enter("delete_lesson", lesson_id)
        row = self._lesson(lesson_id)
        count = sum(1 for (_, lid) in self.cells if lid == lesson_id)
        if count:
            raise JournalError(
                f"Урок має оцінки чи позначки ({count}) — його не можна видалити. "
                "Спершу очистьте клітинки цього уроку."
            )
        ordered = sorted(self.lessons, key=self._lesson_key)
        index = ordered.index(row)
        previous = ordered[index - 1] if index else None
        # як у сервісі: лише попередній урок того самого семестру
        if previous is not None and self._semester_of(previous["date"]) != self._semester_of(row["date"]):
            previous = None
        attached = [c for c in self.columns if c["after"] == lesson_id]
        if previous is not None:
            for column in list(attached):
                if any(c["kind"] == column["kind"] and c["after"] == previous["id"] for c in self.columns):
                    if any(g is not None or na for g, na in column["grades"].values()):
                        raise JournalError("Не можна видалити урок: стовпчик з оцінками мав би стати після "
                                           "попереднього уроку, де вже є такий стовпчик.")
                    self.columns.remove(column)
                    attached.remove(column)
        for column in attached:
            column["after"] = previous["id"] if previous is not None else None
            if previous is not None:
                column["date"] = previous["date"]
        self.lessons.remove(row)

    def create_column(self, teacher_id, journal_id, kind, after_lesson_id) -> ExtraColumnInfo:
        self._enter("create_column", journal_id, kind, after_lesson_id)
        after = self._lesson(after_lesson_id)
        if any(c["kind"] == kind and c["after"] == after_lesson_id for c in self.columns):
            raise JournalError(COLUMN_EXISTS)
        column_id = self.add_column(kind, after_lesson_id)
        return next(i for i in self._extra_infos(self._semester_of(after["date"])) if i.id == column_id)

    def move_column(self, teacher_id, column_id, after_lesson_id) -> ExtraColumnInfo:
        self._enter("move_column", column_id, after_lesson_id)
        column = self._column(column_id)
        after = self._lesson(after_lesson_id)
        if any(c is not column and c["kind"] == column["kind"] and c["after"] == after_lesson_id
               for c in self.columns):
            raise JournalError(COLUMN_EXISTS)
        column["after"] = after_lesson_id
        column["date"] = after["date"]
        return next(i for i in self._extra_infos(self._semester_of(after["date"])) if i.id == column_id)

    def delete_column(self, teacher_id, column_id) -> None:
        self._enter("delete_column", column_id)
        column = self._column(column_id)
        if column["kind"] == "notebook":
            count = sum(1 for g, _ in column["grades"].values() if g is not None)
            if count:
                raise JournalError(
                    f"У стовпчику «Зошит» є оцінки ({count}) — його не можна видалити. Спершу очистьте їх."
                )
        self.columns.remove(column)

    def set_override(self, teacher_id, journal_id, student_id, key, grade, na=False):
        self._enter("set_override", journal_id, student_id, key, grade, na)
        student = next((s for s in self.students if s.id == student_id), None)
        if student is None:
            raise JournalError("Учня не знайдено")
        if student.archived:
            raise JournalError("Учень вибув — його клітинки лише для перегляду")
        _check_grade(grade)
        kind, number = key
        if kind == "notebook" and na:
            raise JournalError("Для «Зошита» н/а не ставиться")
        if kind in ("thematic", "notebook"):
            column = self._column(number)
            if column["kind"] != kind:
                raise JournalError("Стовпчик не знайдено")
            if grade is None and not na:
                column["grades"].pop(student_id, None)
            else:
                column["grades"][student_id] = (grade, na)
        elif kind in ("semester", "annual"):
            final_key = (student_id, kind, number)
            if grade is None and not na:
                self.finals.pop(final_key, None)
            else:
                self.finals[final_key] = (grade, na)
        else:
            raise JournalError("Невідомий стовпчик")
        return self.student_computed(teacher_id, journal_id, student_id)

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
        self._lesson(lesson_id)
        student = next((s for s in self.students if s.id == student_id), None)
        if student is None:
            raise JournalError("Учня не знайдено")
        if student.archived:
            raise JournalError("Учень вибув — його клітинки лише для перегляду")
        _check_grade(grade)
        if grade is not None and attendance in ("absent", "sick"):
            raise JournalError("Відсутньому учню не можна поставити оцінку")
        comment = _clean(comment, MAX_COMMENT, "Коментар")
        key = (student_id, lesson_id)
        if attendance == "present" and grade is None and comment is None:
            self.cells.pop(key, None)
            return None
        cell = CellInfo(attendance, grade, comment)
        self.cells[key] = cell
        return cell
