from sqlalchemy import Boolean, ForeignKey, SmallInteger, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from journal.models.base import Base, TimestampMixin


class SchoolClass(TimestampMixin, Base):
    """Клас учнів, напр. «9-А» у навчальному році «2026-2027»."""

    __tablename__ = "classes"
    __table_args__ = (UniqueConstraint("teacher_id", "name", "school_year"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    teacher_id: Mapped[int] = mapped_column(ForeignKey("teachers.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(20))
    school_year: Mapped[str] = mapped_column(String(9))  # "2026-2027"
    archived: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")

    teacher: Mapped["Teacher"] = relationship(back_populates="classes")  # noqa: F821
    students: Mapped[list["Student"]] = relationship(
        back_populates="school_class", order_by="Student.position", cascade="all, delete-orphan"
    )
    # Клас із журналами видаляти не можна (RESTRICT у БД); ORM журналів не чіпає.
    journals: Mapped[list["Journal"]] = relationship(  # noqa: F821
        back_populates="school_class", cascade="save-update, merge", passive_deletes="all"
    )


class Student(TimestampMixin, Base):
    """Учень класу.

    position — номер у паперовому журналі: 1..N серед активних учнів за українським алфавітом,
    у вибулих (archived) — 0. Це похідне значення: ClassService перераховує його після кожної
    зміни списку. UNIQUE(class_id, position) свідомо не додано — він заважав би перенумерації
    «на місці», а вибулі мають однаковий 0 (рішення рецензента, етап 3).
    """

    __tablename__ = "students"

    id: Mapped[int] = mapped_column(primary_key=True)
    class_id: Mapped[int] = mapped_column(ForeignKey("classes.id", ondelete="CASCADE"), index=True)
    full_name: Mapped[str] = mapped_column(String(150))
    position: Mapped[int] = mapped_column(SmallInteger)
    archived: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")

    school_class: Mapped[SchoolClass] = relationship(back_populates="students")
