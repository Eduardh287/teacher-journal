from datetime import date

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    Enum,
    ForeignKey,
    Index,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from journal.models.base import Base, TimestampMixin
from journal.models.enums import Attendance, ExtraColumnKind, FinalGradeKind, LessonType

GRADE_RANGE = "grade BETWEEN 1 AND 12"
# Рівно одне з двох: оцінка або ручна позначка «н/а».
GRADE_OR_NA = "(grade IS NOT NULL AND NOT is_na) OR (grade IS NULL AND is_na)"


def _text_enum(enum_cls, name: str) -> Enum:
    """Зберігаємо enum як VARCHAR + CHECK, а не як тип PostgreSQL: простіше змінювати міграціями."""
    return Enum(
        enum_cls,
        name=name,
        native_enum=False,
        create_constraint=True,
        length=20,
        values_callable=lambda e: [m.value for m in e],
    )


class Subject(Base):
    """Предмет (довідник): алгебра, геометрія, математика, фізика + додані викладачкою."""

    __tablename__ = "subjects"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(50), unique=True)


class Journal(TimestampMixin, Base):
    """Журнал = клас + предмет на навчальний рік. Семестр визначається уроком."""

    __tablename__ = "journals"
    __table_args__ = (
        UniqueConstraint("class_id", "subject_id"),
        *(
            CheckConstraint(f"{c} BETWEEN 1 AND 12", name=c)
            for c in ("s1_start_month", "s1_end_month", "s2_start_month", "s2_end_month")
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    class_id: Mapped[int] = mapped_column(ForeignKey("classes.id", ondelete="RESTRICT"), index=True)
    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id", ondelete="RESTRICT"))
    # Знімок меж семестрів: для класів у роботі дорівнює глобальним з Налаштувань, в архіві — заморожений.
    s1_start_month: Mapped[int] = mapped_column(SmallInteger, default=9, server_default="9")
    s1_end_month: Mapped[int] = mapped_column(SmallInteger, default=12, server_default="12")
    s2_start_month: Mapped[int] = mapped_column(SmallInteger, default=1, server_default="1")
    s2_end_month: Mapped[int] = mapped_column(SmallInteger, default=6, server_default="6")

    school_class: Mapped["SchoolClass"] = relationship(back_populates="journals")  # noqa: F821
    subject: Mapped[Subject] = relationship()
    # Журнал з уроками чи оцінками видаляти не можна: БД відмовляє (RESTRICT), а ORM
    # не повинна ні видаляти дітей, ні обнуляти зовнішні ключі (passive_deletes="all").
    lessons: Mapped[list["Lesson"]] = relationship(
        back_populates="journal",
        order_by="(Lesson.lesson_date, Lesson.id)",
        cascade="save-update, merge",
        passive_deletes="all",
    )
    final_grades: Mapped[list["FinalGrade"]] = relationship(
        back_populates="journal", cascade="save-update, merge", passive_deletes="all"
    )
    extra_columns: Mapped[list["ExtraColumn"]] = relationship(
        back_populates="journal", cascade="save-update, merge", passive_deletes="all"
    )


class Lesson(TimestampMixin, Base):
    """Урок (стовпець у таблиці журналу)."""

    __tablename__ = "lessons"
    __table_args__ = (
        CheckConstraint("semester IN (1, 2)", name="semester"),
        Index("ix_lessons_journal_semester_date", "journal_id", "semester", "lesson_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    journal_id: Mapped[int] = mapped_column(ForeignKey("journals.id", ondelete="RESTRICT"))
    lesson_date: Mapped[date] = mapped_column(Date)
    semester: Mapped[int] = mapped_column(SmallInteger)
    topic: Mapped[str | None] = mapped_column(String(255))
    homework: Mapped[str | None] = mapped_column(Text)  # домашнє завдання (до 500 символів, перевіряє сервіс)
    lesson_type: Mapped[LessonType] = mapped_column(
        _text_enum(LessonType, "lesson_type"), default=LessonType.REGULAR, server_default="regular"
    )

    journal: Mapped[Journal] = relationship(back_populates="lessons")
    entries: Mapped[list["LessonEntry"]] = relationship(
        back_populates="lesson", cascade="all, delete-orphan"
    )


class LessonEntry(Base):
    """Клітинка журналу: учень × урок — відвідування, оцінка 1–12, коментар."""

    __tablename__ = "lesson_entries"
    __table_args__ = (CheckConstraint(GRADE_RANGE, name="grade_range"),)

    lesson_id: Mapped[int] = mapped_column(
        ForeignKey("lessons.id", ondelete="CASCADE"), primary_key=True
    )
    student_id: Mapped[int] = mapped_column(
        ForeignKey("students.id", ondelete="RESTRICT"), primary_key=True, index=True
    )
    attendance: Mapped[Attendance] = mapped_column(
        _text_enum(Attendance, "attendance"), default=Attendance.PRESENT, server_default="present"
    )
    grade: Mapped[int | None] = mapped_column(SmallInteger)
    comment: Mapped[str | None] = mapped_column(Text)

    lesson: Mapped[Lesson] = relationship(back_populates="entries")
    student: Mapped["Student"] = relationship()  # noqa: F821


class FinalGrade(Base):
    """Підсумкова оцінка: за 1-й семестр, 2-й семестр або річна."""

    __tablename__ = "final_grades"
    __table_args__ = (
        CheckConstraint(GRADE_RANGE, name="grade_range"),
        CheckConstraint(GRADE_OR_NA, name="grade_or_na"),
    )

    journal_id: Mapped[int] = mapped_column(
        ForeignKey("journals.id", ondelete="RESTRICT"), primary_key=True
    )
    student_id: Mapped[int] = mapped_column(
        ForeignKey("students.id", ondelete="RESTRICT"), primary_key=True
    )
    kind: Mapped[FinalGradeKind] = mapped_column(
        _text_enum(FinalGradeKind, "final_grade_kind"), primary_key=True
    )
    # Рядок = ручне значення (override): оцінка або «н/а». Автоматичні значення не зберігаються.
    grade: Mapped[int | None] = mapped_column(SmallInteger)
    is_na: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")

    journal: Mapped[Journal] = relationship(back_populates="final_grades")
    student: Mapped["Student"] = relationship()  # noqa: F821


class ExtraColumn(TimestampMixin, Base):
    """Стовпчик без дати: «Тематична» або «Зошит».

    after_lesson_id — урок-якір: стовпчик стоїть одразу після нього (і після всіх стовпчиків, доданих
    до нього раніше), а уроки, створені пізніше навіть того самого дня, — після стовпчика. Якщо якоря
    немає (NULL: урок-якір видалено першим у журналі або дані до міграції), стовпчик стоїть на
    дату after_date ПЕРЕД усіма уроками цієї дати. after_date — дата якоря (семестр, межі семестрів).
    Один стовпчик виду після одного уроку.
    """

    __tablename__ = "extra_columns"
    __table_args__ = (
        CheckConstraint("semester IN (1, 2)", name="semester"),
        Index(
            "uq_extra_columns_journal_id_kind_after_lesson_id",
            "journal_id", "kind", "after_lesson_id",
            unique=True,
            postgresql_where=text("after_lesson_id IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    journal_id: Mapped[int] = mapped_column(ForeignKey("journals.id", ondelete="RESTRICT"))
    kind: Mapped[ExtraColumnKind] = mapped_column(_text_enum(ExtraColumnKind, "extra_column_kind"))
    semester: Mapped[int] = mapped_column(SmallInteger)
    after_date: Mapped[date] = mapped_column(Date)
    after_lesson_id: Mapped[int | None] = mapped_column(
        ForeignKey("lessons.id", ondelete="SET NULL"), index=True
    )

    journal: Mapped[Journal] = relationship(back_populates="extra_columns")
    grades: Mapped[list["ExtraGrade"]] = relationship(
        back_populates="column", cascade="all, delete-orphan"
    )


class ExtraGrade(Base):
    """Оцінка в extra-стовпчику: для тематичної — ручне значення, для «Зошита» — сама оцінка."""

    __tablename__ = "extra_grades"
    __table_args__ = (
        CheckConstraint(GRADE_RANGE, name="grade_range"),
        CheckConstraint(GRADE_OR_NA, name="grade_or_na"),
    )

    column_id: Mapped[int] = mapped_column(
        ForeignKey("extra_columns.id", ondelete="CASCADE"), primary_key=True
    )
    student_id: Mapped[int] = mapped_column(
        ForeignKey("students.id", ondelete="RESTRICT"), primary_key=True, index=True
    )
    grade: Mapped[int | None] = mapped_column(SmallInteger)
    is_na: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")

    column: Mapped[ExtraColumn] = relationship(back_populates="grades")
    student: Mapped["Student"] = relationship()  # noqa: F821
