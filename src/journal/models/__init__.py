"""Моделі БД. Імпорт усіх класів тут потрібен, щоб Alembic бачив усі таблиці."""
from journal.models.base import Base
from journal.models.enums import Attendance, ExtraColumnKind, FinalGradeKind, LessonType
from journal.models.journal import (
    ExtraColumn,
    ExtraGrade,
    FinalGrade,
    Journal,
    Lesson,
    LessonEntry,
    Subject,
)
from journal.models.school_class import SchoolClass, Student
from journal.models.teacher import Teacher

__all__ = [
    "Attendance",
    "Base",
    "ExtraColumn",
    "ExtraColumnKind",
    "ExtraGrade",
    "FinalGrade",
    "FinalGradeKind",
    "Journal",
    "Lesson",
    "LessonEntry",
    "LessonType",
    "SchoolClass",
    "Student",
    "Subject",
    "Teacher",
]
