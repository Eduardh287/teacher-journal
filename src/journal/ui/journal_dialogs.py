"""Діалоги сторінки «Журнали»: новий журнал, урок, коментар, підтвердження видалення уроку й журналу."""
from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import date
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QTextCharFormat
from PySide6.QtWidgets import (
    QComboBox,
    QCalendarWidget,
    QDateEdit,
    QHBoxLayout,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QWidget,
)

from journal.services.grid_text import EXTRA_COLUMN_TYPES, LESSON_TYPES
from journal.services.journal_types import (
    MAX_COMMENT,
    MAX_HOMEWORK,
    MAX_TOPIC,
    JournalApi,
    JournalCandidate,
    JournalError,
    ExtraColumnInfo,
    JournalInfo,
    LessonInfo,
    LessonTypeCode,
    SemesterConflict,
)
from journal.services.semesters import SemesterBoundaries, SemesterError
from journal.ui import theme
from journal.ui.semester_widgets import SemesterBoundsEditor, conflict_text
from journal.ui.widgets import FormDialog, button, field, label

ApiFactory = Callable[[], AbstractContextManager[JournalApi]]

DELETE_WORD = "видалити"
DATELESS_HINT = "Для «Тематичної» і «Зошита» дата, тема й д/з не вказуються"
NO_LESSONS_TEXT = "Спершу створіть урок у цьому семестрі"

class _ApiDialog(FormDialog):
    """Основа: заголовок, рядок помилки й безпечний виклик сервісу журналів."""

    def __init__(self, title: str, teacher_id: int, api_factory: ApiFactory, parent: QWidget | None = None) -> None:
        super().__init__(title, parent)
        self.teacher_id = teacher_id
        self.api_factory = api_factory

    def run_service(self, action: Callable[[JournalApi], Any]) -> tuple[bool, Any]:
        """Виконує action в одній транзакції. Повертає (успіх, результат)."""

        def call():
            with self.api_factory() as api:
                return action(api)

        return self.run(call, JournalError, "Помилка під час роботи з журналами")


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
            self.submit_button: QPushButton | None = self.add_submit("Створити", self._on_submit)
        else:
            self.body.addWidget(self.hint_label)
            self.body.addWidget(self.error_label)
            self.submit_button = None  # немає чого створювати: лише «Закрити»
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
        after_lesson_id: int | None = None,
    ) -> None:
        super().__init__("Редагування уроку" if lesson else "Новий урок", teacher_id, api_factory, parent)
        self.journal_id = journal_id
        self.lesson = lesson
        # Останній урок відкритого семестру: після нього ставиться «Тематична»/«Зошит».
        self.after_lesson_id = after_lesson_id
        self._saved_inputs: tuple | None = None
        self.result_info: LessonInfo | None = None
        self.result_column: ExtraColumnInfo | None = None

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
        self.date_edit.setDate(start)

        self.type_combo = QComboBox()
        for code, (name, _abbr) in LESSON_TYPES.items():
            self.type_combo.addItem(name, code)
        if lesson:
            self.type_combo.setCurrentIndex(self.type_combo.findData(lesson.lesson_type))
        else:  # стовпчики без дати — лише при створенні, після розділювача
            self.type_combo.insertSeparator(self.type_combo.count())
            for code, (name, _abbr) in EXTRA_COLUMN_TYPES.items():
                self.type_combo.addItem(name, code)
            self.type_combo.currentIndexChanged.connect(self._on_type_changed)

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
        self.dateless_hint = label(DATELESS_HINT, muted=True, wrap=True)
        self.dateless_hint.hide()
        self.body.addWidget(self.dateless_hint)
        self.body.addWidget(self.error_label)
        self.add_submit("Зберегти" if lesson else "Створити", self._on_submit)
        if focus_topic:  # подвійний клік по темі в панелі уроків: одразу правимо тему
            self.topic_edit.setFocus()
            self.topic_edit.selectAll()

    def is_dateless(self) -> bool:
        return self.type_combo.currentData() in EXTRA_COLUMN_TYPES

    def _on_type_changed(self) -> None:
        """«Тематична»/«Зошит»: дата, тема й д/з не вводяться (порожні й сірі); повернення до уроку — знову доступні."""
        dateless = self.is_dateless()
        if dateless:
            self._saved_inputs = (
                self.date_edit.date(), self.topic_edit.text(), self.homework_edit.toPlainText()
            )
            self.topic_edit.clear()
            self.homework_edit.clear()
        elif getattr(self, "_saved_inputs", None) is not None:
            qd, topic, homework = self._saved_inputs
            self.date_edit.setDate(qd)
            self.topic_edit.setText(topic)
            self.homework_edit.setPlainText(homework)
            self._saved_inputs = None
        for widget in (self.date_edit, self.topic_edit, self.homework_edit):
            widget.setEnabled(not dateless)
        self.dateless_hint.setVisible(dateless)
        self.error_label.hide()

    def _limit_homework(self) -> None:
        text = self.homework_edit.toPlainText()
        if len(text) > MAX_HOMEWORK:
            self.homework_edit.setPlainText(text[:MAX_HOMEWORK])
            cursor = self.homework_edit.textCursor()
            cursor.movePosition(cursor.MoveOperation.End)
            self.homework_edit.setTextCursor(cursor)

    def _submit_column(self, kind: str) -> None:
        if self.after_lesson_id is None:
            self.show_error(NO_LESSONS_TEXT)
            return
        after_id = self.after_lesson_id
        ok, info = self.run_service(
            lambda api: api.create_column(self.teacher_id, self.journal_id, kind, after_id)
        )
        if ok:
            self.result_column = info
            self.accept()

    def _on_submit(self) -> None:
        if self.lesson is None and self.is_dateless():
            self._submit_column(self.type_combo.currentData())
            return
        lesson_date = self.date_edit.date().toPython()
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


class CommentDialog(FormDialog):
    """Багаторядковий коментар до клітинки (до 500 символів)."""

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__("Коментар", parent, heading="Коментар до клітинки")
        layout = self.body
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


class _TypedConfirmDialog(FormDialog):
    """Підтвердження словом: кнопка «Видалити» активується лише після введення «видалити»."""

    def __init__(
        self,
        window_title: str,
        heading: str,
        text: str,
        parent: QWidget | None = None,
        *,
        word: str = DELETE_WORD,
        confirm_text: str = "Видалити",
    ) -> None:
        super().__init__(window_title, parent, heading=heading)
        self._word = word
        layout = self.body
        layout.addWidget(label(f"{text} Щоб підтвердити, введіть «{word}».", wrap=True))
        self.confirm_edit = QLineEdit()
        self.confirm_edit.setPlaceholderText(word)
        self.confirm_edit.textChanged.connect(self._update)
        layout.addWidget(self.confirm_edit)
        row = QHBoxLayout()
        cancel = button("Скасувати")
        cancel.setDefault(True)
        cancel.clicked.connect(self.reject)
        self.delete_button = button(confirm_text)
        self.delete_button.setEnabled(False)
        self.delete_button.clicked.connect(self.accept)
        row.addStretch(1)
        row.addWidget(cancel)
        row.addWidget(self.delete_button)
        layout.addLayout(row)

    def _update(self, text: str) -> None:
        self.delete_button.setEnabled(text.strip().lower() == self._word)


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


SETTINGS_ONLY_TEXT = "Змінюється в Налаштуваннях"


class JournalSettingsDialog(_ApiDialog):
    """Межі семестрів окремого журналу. Змінюються лише для архівного класу."""

    def __init__(self, teacher_id: int, api_factory: ApiFactory, info: JournalInfo, parent: QWidget | None = None) -> None:
        super().__init__("Налаштування журналу", teacher_id, api_factory, parent)
        self.info = info
        self.result_info: JournalInfo | None = None
        self.editable = info.class_archived

        self.body.addWidget(label(f"{info.class_name} · {info.subject_name} · {info.school_year}", muted=True))
        self.editor = SemesterBoundsEditor(info.boundaries, spacing=14)
        self.combos = self.editor.combos
        self.body.addWidget(self.editor)
        self.body.addWidget(label("Інші місяці — канікули", muted=True))

        self.note_label = label(SETTINGS_ONLY_TEXT, muted=True, wrap=True)
        self.save_button = button("Зберегти", variant="primary")
        self.save_button.setMinimumHeight(40)
        self.save_button.setDefault(True)
        self.save_button.clicked.connect(self._on_save)
        if self.editable:
            self.note_label.hide()
        else:
            self.editor.setEnabled(False)
            self.save_button.hide()
        self.body.addWidget(self.note_label)
        self.body.addWidget(self.error_label)
        self.body.addWidget(self.save_button)

    def selected_boundaries(self) -> SemesterBoundaries:
        return self.editor.boundaries()

    def error_text(self, error: Exception) -> str:
        if isinstance(error, SemesterConflict):  # показуємо уроки й повертаємо попередні межі
            self.editor.set_boundaries(self.info.boundaries)
            return conflict_text(error.conflicts)
        return str(error)

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
        ok, info = self.run_service(lambda api: api.set_journal_semesters(self.teacher_id, journal_id, boundaries))
        if ok:
            self.result_info = info
            self.accept()
