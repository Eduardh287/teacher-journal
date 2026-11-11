"""Моделі БД. Імпорт усіх класів тут потрібен, щоб Alembic бачив усі таблиці."""
from journal.models.base import Base
from journal.models.enums import Attendance, FinalGradeKind, LessonType
from journal.models.journal import FinalGrade, Journal, Lesson, LessonEntry, Subject
from journal.models.school_class import SchoolClass, Student
from journal.models.teacher import Teacher

__all__ = [
    "Attendance",
    "Base",
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
