"""Діалоги сторінки «Журнали»: новий журнал, урок, коментар, підтвердження видалення уроку й журналу."""
import logging
from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import date
from typing import Any

from PySide6.QtCore import QDate, Qt
from PySide6.QtGui import QColor, QTextCharFormat
from PySide6.QtWidgets import (
    QComboBox,
    QCalendarWidget,
    QDateEdit,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from journal.services.journal_types import (
    MAX_COMMENT,
    MAX_HOMEWORK,
    MAX_TOPIC,
    JournalApi,
    JournalCandidate,
    JournalError,
    JournalInfo,
    LessonInfo,
    LessonTypeCode,
    SemesterConflict,
)
from journal.services.semesters import MONTHS_UA, SemesterBoundaries, SemesterError
from journal.ui import theme
from journal.ui.widgets import button, field, label

ApiFactory = Callable[[], AbstractContextManager[JournalApi]]

SAVE_ERROR_TEXT = "Не вдалося зберегти зміни"
DELETE_WORD = "видалити"

# Тип уроку: код -> (назва, скорочення в заголовку стовпця)
LESSON_TYPES: dict[str, tuple[str, str]] = {
    "regular": ("Звичайний урок", ""),
    "test": ("Контрольна робота", "КР"),
    "lab": ("Лабораторна робота", "ЛР"),
    "independent": ("Самостійна робота", "СР"),
    "quiz": ("Тест", "Т"),  # етап 6, відгук викладачки
    "project": ("Проєкт", "Пр"),
}

# Стовпчики без дати (етап 6): назва, скорочення в заголовку (погоджено з викладачкою).
EXTRA_COLUMN_TYPES: dict[str, tuple[str, str]] = {
    "thematic": ("Тематична", "Тем"),
    "notebook": ("Зошит", "Зош"),
}
FINAL_COLUMN_TITLES: dict[str, tuple[str, str]] = {
    "semester": ("Семестрова", "Сем."),
    "annual": ("Річна", "Річна"),
}


class _ApiDialog(QDialog):
    """Основа: заголовок, рядок помилки й безпечний виклик сервісу журналів."""

    def __init__(self, title: str, teacher_id: int, api_factory: ApiFactory, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(440)
        self.teacher_id = teacher_id
        self.api_factory = api_factory

        self.error_label = QLabel()
        self.error_label.setProperty("error", True)
        self.error_label.setWordWrap(True)
        self.error_label.hide()

        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(32, 28, 32, 28)
        self.body.setSpacing(14)
        self.body.addWidget(label(title, object_name="EmptyTitle"))

    def show_error(self, text: str) -> None:
        self.error_label.setText(text)
        self.error_label.show()

    def run_service(self, action: Callable[[JournalApi], Any]) -> tuple[bool, Any]:
        """Виконує action в одній транзакції; JournalError ловимо поза блоком with (відкат)."""
        self.error_label.hide()
        try:
            with self.api_factory() as api:
                result = action(api)
        except JournalError as error:
            self.show_error(str(error))
            return False, None
        except Exception:
            logging.exception("Помилка під час роботи з журналами")
            self.show_error(SAVE_ERROR_TEXT)
            return False, None
        return True, result


class NewJournalDialog(_ApiDialog):
    """Створення журналу: вибір класу та предмета серед ще не створених пар."""

    def __init__(self, teacher_id: int, api_factory: ApiFactory, parent: QWidget | None = None) -> None:
        super().__init__("Новий журнал", teacher_id, api_factory, parent)
        self.result_info: JournalInfo | None = None
        ok, candidates = self.run_service(lambda api: api.list_journal_candidates(teacher_id))
        self.candidates: list[JournalCandidate] = candidates if ok else []

        self.class_combo = QComboBox()
        self.subject_combo = QComboBox()
        self.hint_label = label(
            "Немає класів чи предметів для нового журналу. Спершу створіть клас на сторінці «Класи».",
            muted=True,
            wrap=True,
        )
        self.submit_button = button("Створити", variant="primary")
        self.submit_button.setMinimumHeight(40)
        self.submit_button.setDefault(True)
        self.submit_button.clicked.connect(self._on_submit)

        if self.candidates:
            seen: set[int] = set()
            for c in self.candidates:
                if c.class_id not in seen:
                    seen.add(c.class_id)
                    self.class_combo.addItem(f"{c.class_name} · {c.school_year}", c.class_id)
            self.class_combo.currentIndexChanged.connect(self._fill_subjects)
            self._fill_subjects()
            self.body.addWidget(field("КЛАС", self.class_combo))
            self.body.addWidget(field("ПРЕДМЕТ", self.subject_combo))
            self.body.addWidget(self.error_label)
            self.body.addWidget(self.submit_button)
        else:
            self.body.addWidget(self.hint_label)
            self.body.addWidget(self.error_label)
            self.submit_button.setEnabled(False)
            close_button = button("Закрити")
            close_button.clicked.connect(self.reject)
            self.body.addWidget(close_button)

    def _fill_subjects(self) -> None:
        class_id = self.class_combo.currentData()
        self.subject_combo.clear()
        for c in self.candidates:
            if c.class_id == class_id:
                self.subject_combo.addItem(c.subject_name, c.subject_id)

    def _on_submit(self) -> None:
        class_id, subject_id = self.class_combo.currentData(), self.subject_combo.currentData()
        if class_id is None or subject_id is None:
            return
        ok, info = self.run_service(lambda api: api.create_journal(self.teacher_id, class_id, subject_id))
        if ok:
            self.result_info = info
            self.accept()


class LessonDialog(_ApiDialog):
    """Створення або редагування уроку (lesson=None — створення)."""

    def __init__(
        self,
        teacher_id: int,
        api_factory: ApiFactory,
        journal_id: int,
        lesson: LessonInfo | None = None,
        parent: QWidget | None = None,
        *,
        focus_topic: bool = False,
    ) -> None:
        super().__init__("Редагування уроку" if lesson else "Новий урок", teacher_id, api_factory, parent)
        self.journal_id = journal_id
        self.lesson = lesson
        self.result_info: LessonInfo | None = None

        self.date_edit = QDateEdit()
        self.date_edit.setCalendarPopup(True)
        # Номери тижнів (44, 45…) викладачці не потрібні.
        self.date_edit.calendarWidget().setVerticalHeaderFormat(
            QCalendarWidget.VerticalHeaderFormat.NoVerticalHeader
        )
        weekend = QTextCharFormat()
        weekend.setForeground(QColor(theme.color("danger")))
        for day in (Qt.DayOfWeek.Saturday, Qt.DayOfWeek.Sunday):
            self.date_edit.calendarWidget().setWeekdayTextFormat(day, weekend)
        self.date_edit.setDisplayFormat("dd.MM.yyyy")
        start = lesson.lesson_date if lesson else date.today()
        self.date_edit.setDate(QDate(start.year, start.month, start.day))

        self.type_combo = QComboBox()
        for code, (name, _abbr) in LESSON_TYPES.items():
            self.type_combo.addItem(name, code)
        if lesson:
            self.type_combo.setCurrentIndex(self.type_combo.findData(lesson.lesson_type))

        self.topic_edit = QLineEdit()
        self.topic_edit.setPlaceholderText("необов'язково")
        self.topic_edit.setMaxLength(MAX_TOPIC)
        if lesson and lesson.topic:
            self.topic_edit.setText(lesson.topic)

        self.body.addWidget(field("ДАТА", self.date_edit))
        self.body.addWidget(field("ТИП", self.type_combo))
        self.homework_edit = QPlainTextEdit()
        self.homework_edit.setPlaceholderText("необов'язково")
        self.homework_edit.setFixedHeight(72)
        self.homework_edit.setTabChangesFocus(True)
        if lesson and lesson.homework:
            self.homework_edit.setPlainText(lesson.homework)
        self.homework_edit.textChanged.connect(self._limit_homework)

        self.body.addWidget(field("ТЕМА", self.topic_edit))
        self.body.addWidget(field("ДОМАШНЄ ЗАВДАННЯ", self.homework_edit))
        self.body.addWidget(self.error_label)
        submit = button("Зберегти" if lesson else "Створити", variant="primary")
        submit.setDefault(True)
        submit.setMinimumHeight(40)
        submit.clicked.connect(self._on_submit)
        self.body.addWidget(submit)
        if focus_topic:  # подвійний клік по темі в панелі уроків: одразу правимо тему
            self.topic_edit.setFocus()
            self.topic_edit.selectAll()

    def _limit_homework(self) -> None:
        text = self.homework_edit.toPlainText()
        if len(text) > MAX_HOMEWORK:
            self.homework_edit.setPlainText(text[:MAX_HOMEWORK])
            cursor = self.homework_edit.textCursor()
            cursor.movePosition(cursor.MoveOperation.End)
            self.homework_edit.setTextCursor(cursor)

    def _on_submit(self) -> None:
        qd = self.date_edit.date()
        lesson_date = date(qd.year(), qd.month(), qd.day())
        lesson_type: LessonTypeCode = self.type_combo.currentData()
        topic = self.topic_edit.text()
        homework = self.homework_edit.toPlainText().strip()
        if self.lesson is None:
            ok, info = self.run_service(
                lambda api: api.create_lesson(
                    self.teacher_id, self.journal_id, lesson_date, lesson_type, topic, homework
                )
            )
        else:
            lesson_id = self.lesson.id
            ok, info = self.run_service(
                lambda api: api.update_lesson(
                    self.teacher_id, lesson_id, lesson_date, lesson_type, topic, homework
                )
            )
        if ok:
            self.result_info = info
            self.accept()


class CommentDialog(QDialog):
    """Багаторядковий коментар до клітинки (до 500 символів)."""

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Коментар")
        self.setMinimumWidth(440)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(14)
        layout.addWidget(label("Коментар до клітинки", object_name="EmptyTitle"))
        self.edit = QPlainTextEdit()
        self.edit.setMinimumHeight(140)
        self.edit.setTabChangesFocus(True)
        self.edit.setPlainText(text)
        self.edit.textChanged.connect(self._limit)
        layout.addWidget(self.edit)
        layout.addWidget(label(f"До {MAX_COMMENT} символів. Порожній коментар буде видалено.", muted=True))
        row = QHBoxLayout()
        cancel = button("Скасувати")
        cancel.clicked.connect(self.reject)
        save = button("Зберегти", variant="primary")
        save.setDefault(True)
        save.clicked.connect(self.accept)
        row.addStretch(1)
        row.addWidget(cancel)
        row.addWidget(save)
        layout.addLayout(row)

    def _limit(self) -> None:
        if len(self.edit.toPlainText()) > MAX_COMMENT:
            self.edit.setPlainText(self.edit.toPlainText()[:MAX_COMMENT])
            cursor = self.edit.textCursor()
            cursor.movePosition(cursor.MoveOperation.End)
            self.edit.setTextCursor(cursor)

    def text(self) -> str:
        return self.edit.toPlainText().strip()


class _TypedConfirmDialog(QDialog):
    """Підтвердження словом: кнопка «Видалити» активується лише після введення «видалити»."""

    def __init__(self, window_title: str, heading: str, text: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(window_title)
        self.setMinimumWidth(440)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(14)
        layout.addWidget(label(heading, object_name="EmptyTitle"))
        layout.addWidget(label(f"{text} Щоб підтвердити, введіть «{DELETE_WORD}».", wrap=True))
        self.confirm_edit = QLineEdit()
        self.confirm_edit.setPlaceholderText(DELETE_WORD)
        self.confirm_edit.textChanged.connect(self._update)
        layout.addWidget(self.confirm_edit)
        row = QHBoxLayout()
        cancel = button("Скасувати")
        cancel.setDefault(True)
        cancel.clicked.connect(self.reject)
        self.delete_button = button("Видалити")
        self.delete_button.setEnabled(False)
        self.delete_button.clicked.connect(self.accept)
        row.addStretch(1)
        row.addWidget(cancel)
        row.addWidget(self.delete_button)
        layout.addLayout(row)

    def _update(self, text: str) -> None:
        self.delete_button.setEnabled(text.strip().lower() == DELETE_WORD)


class DeleteLessonDialog(_TypedConfirmDialog):
    """Видалення уроку з оцінками (підтвердження словом «видалити»)."""

    def __init__(self, lesson: LessonInfo, parent: QWidget | None = None) -> None:
        self.lesson = lesson
        super().__init__(
            "Видалити урок",
            "Видалити урок?",
            f"Урок {lesson.lesson_date:%d.%m.%Y} містить відміток і оцінок: {lesson.entry_count}. "
            "Їх буде видалено безповоротно.",
            parent,
        )


class DeleteJournalDialog(_TypedConfirmDialog):
    """Видалення журналу разом з усіма уроками, відмітками та оцінками."""

    def __init__(self, journal: JournalInfo, lesson_count: int, parent: QWidget | None = None) -> None:
        self.journal = journal
        self.lesson_count = lesson_count
        super().__init__(
            "Видалити журнал",
            "Видалити журнал?",
            f"Журнал «{journal.class_name} · {journal.subject_name}» містить уроків: {lesson_count}. "
            "Разом з ним буде безповоротно видалено всі уроки, відмітки та оцінки.",
            parent,
        )


CONFLICT_LIMIT = 10
SETTINGS_ONLY_TEXT = "Змінюється в Налаштуваннях"


def conflict_text(conflicts: list) -> str:
    """«Зміну не збережено…» і перелік уроків «9-А · Алгебра — 15.01.2027» (перші 10, далі «і ще N»)."""
    lines = [
        f"{c.class_name} · {c.subject_name} — {c.lesson_date:%d.%m.%Y}" for c in conflicts[:CONFLICT_LIMIT]
    ]
    if len(conflicts) > CONFLICT_LIMIT:
        lines.append(f"і ще {len(conflicts) - CONFLICT_LIMIT}")
    return "Зміну не збережено: ці уроки потрапляють у канікули.\n" + "\n".join(lines)


class JournalSettingsDialog(_ApiDialog):
    """Межі семестрів окремого журналу. Змінюються лише для архівного класу."""

    def __init__(self, teacher_id: int, api_factory: ApiFactory, info: JournalInfo, parent: QWidget | None = None) -> None:
        super().__init__("Налаштування журналу", teacher_id, api_factory, parent)
        self.info = info
        self.result_info: JournalInfo | None = None
        self.editable = info.class_archived
        b = info.boundaries

        self.body.addWidget(label(f"{info.class_name} · {info.subject_name} · {info.school_year}", muted=True))
        self.combos: dict[str, QComboBox] = {}
        for caption, start_key, end_key, start, end in (
            ("I семестр", "s1_start", "s1_end", b.s1_start, b.s1_end),
            ("II семестр", "s2_start", "s2_end", b.s2_start, b.s2_end),
        ):
            row = QHBoxLayout()
            row.setSpacing(8)
            row.addWidget(label(f"{caption}: з"))
            row.addWidget(self._month_combo(start_key, start))
            row.addWidget(label("по"))
            row.addWidget(self._month_combo(end_key, end))
            row.addStretch(1)
            self.body.addLayout(row)
        self.body.addWidget(label("Інші місяці — канікули", muted=True))

        self.note_label = label(SETTINGS_ONLY_TEXT, muted=True, wrap=True)
        self.save_button = button("Зберегти", variant="primary")
        self.save_button.setMinimumHeight(40)
        self.save_button.setDefault(True)
        self.save_button.clicked.connect(self._on_save)
        if self.editable:
            self.note_label.hide()
        else:
            for combo in self.combos.values():
                combo.setEnabled(False)
            self.save_button.hide()
        self.body.addWidget(self.note_label)
        self.body.addWidget(self.error_label)
        self.body.addWidget(self.save_button)

    def _month_combo(self, key: str, month: int) -> QComboBox:
        combo = QComboBox()
        for number, name in enumerate(MONTHS_UA, start=1):
            combo.addItem(name, number)
        combo.setCurrentIndex(month - 1)
        self.combos[key] = combo
        return combo

    def selected_boundaries(self) -> SemesterBoundaries:
        c = self.combos
        return SemesterBoundaries(
            c["s1_start"].currentData(), c["s1_end"].currentData(),
            c["s2_start"].currentData(), c["s2_end"].currentData(),
        )

    def _revert(self) -> None:
        b = self.info.boundaries
        for key, month in (("s1_start", b.s1_start), ("s1_end", b.s1_end), ("s2_start", b.s2_start), ("s2_end", b.s2_end)):
            self.combos[key].setCurrentIndex(month - 1)

    def _on_save(self) -> None:
        if not self.editable:
            return
        self.error_label.hide()
        try:
            boundaries = self.selected_boundaries().validate()
        except SemesterError as error:
            self.show_error(str(error))
            return
        journal_id = self.info.id
        self.error_label.hide()
        try:
            with self.api_factory() as api:
                info = api.set_journal_semesters(self.teacher_id, journal_id, boundaries)
        except SemesterConflict as conflict:
            self.show_error(conflict_text(conflict.conflicts))
            self._revert()
            return
        except JournalError as error:
            self.show_error(str(error))
            return
        except Exception:
            logging.exception("Помилка під час зміни меж семестрів журналу")
            self.show_error(SAVE_ERROR_TEXT)
            return
        self.result_info = info
        self.accept()
