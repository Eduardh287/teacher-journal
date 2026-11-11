"""Перелічення. У БД зберігаються як текст з CHECK-обмеженням (легко розширювати міграціями)."""
import enum


class Attendance(str, enum.Enum):
    PRESENT = "present"  # присутній
    ABSENT = "absent"    # відсутній (н)
    SICK = "sick"        # хворів (хв)
    LATE = "late"        # запізнився


class LessonType(str, enum.Enum):
    REGULAR = "regular"          # звичайний урок
    TEST = "test"                # контрольна робота
    LAB = "lab"                  # лабораторна робота
    INDEPENDENT = "independent"  # самостійна робота


class FinalGradeKind(str, enum.Enum):
    SEMESTER_1 = "semester_1"
    SEMESTER_2 = "semester_2"
    ANNUAL = "annual"
