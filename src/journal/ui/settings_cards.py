"""Картки сторінки «Налаштування»: межі семестрів і довідник предметів (етап 5.2)."""
import logging
import os
from collections.abc import Callable
from contextlib import AbstractContextManager
from functools import partial
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QLineEdit,
    QWidget,
)

from journal.services.journal_types import JournalError, SemesterConflict
from journal.services.semesters import DEFAULT_BOUNDARIES, SemesterBoundaries, SemesterError
from journal.services.settings_service import SettingsService
from journal.services.subject_service import MAX_SUBJECT_NAME, SubjectError, SubjectService
from journal.services.auth_service import AuthError
from journal.logging_setup import log_failure
from journal.ui import auth_dialogs, backup_dialogs
from journal.ui.service_scope import service_scope
from journal.ui.theme import app_settings
from journal.ui.widgets import ElidedLabel, SemesterBoundsEditor, SettingsCard, button, conflict_text, label

GENERIC_ERROR = "Не вдалося зберегти зміни"


class SemestersCard(SettingsCard):
    """Межі семестрів по місяцях; зберігаються одразу для всіх журналів у роботі."""

    def __init__(
        self,
        teacher_id: int,
        service_factory: Callable[[], AbstractContextManager] | None = None,
        on_saved: Callable[[], None] | None = None,
    ) -> None:
        super().__init__("Семестри", "Межі семестрів задаються місяцями. Інші місяці — канікули.")
        self.teacher_id = teacher_id
        self._factory = service_factory or partial(service_scope, SettingsService)
        self._on_saved = on_saved
        self._loaded = DEFAULT_BOUNDARIES

        self.editor = SemesterBoundsEditor(caption_width=72)
        self.s1_start, self.s1_end, self.s2_start, self.s2_end = (
            self.editor.combos[key] for key in SemesterBoundsEditor.KEYS
        )
        self.body.addWidget(self.editor)

        actions = QHBoxLayout()
        self.save_button = button("Зберегти", variant="primary")
        self.save_button.clicked.connect(self._on_save)
        actions.addWidget(self.save_button)
        actions.addStretch(1)
        self.body.addLayout(actions)
        self.add_feedback()
        self.load()

    def boundaries(self) -> SemesterBoundaries:
        return self.editor.boundaries()

    def load(self) -> None:
        try:
            with self._factory() as service:
                loaded = service.get_semesters(self.teacher_id)
        except Exception:
            logging.exception("Не вдалося завантажити межі семестрів")
            self.show_error("Не вдалося завантажити налаштування семестрів")
            return
        self._loaded = loaded
        self.editor.set_boundaries(loaded)

    def _on_save(self) -> None:
        chosen = self.boundaries()
        try:
            with self._factory() as service:
                updated = service.set_semesters(self.teacher_id, chosen)
        except SemesterError as error:
            self.show_error(str(error))
            return
        except SemesterConflict as error:
            self.editor.set_boundaries(self._loaded)
            self.show_error(conflict_text(error.conflicts, header=f"{error}:"))
            return
        except JournalError as error:
            self.show_error(str(error))
            return
        except Exception:
            logging.exception("Не вдалося зберегти межі семестрів")
            self.show_error(GENERIC_ERROR)
            return
        self._loaded = chosen
        self.show_status(f"Збережено. Оновлено журналів: {updated}")
        if self._on_saved is not None:
            self._on_saved()


class SubjectsCard(SettingsCard):
    """Список предметів і додавання власного (рішення автора)."""

    def __init__(
        self,
        service_factory: Callable[[], AbstractContextManager] | None = None,
        on_changed: Callable[[], None] | None = None,
    ) -> None:
        super().__init__("Предмети", "Предмети, для яких можна створювати журнали. Додайте свій, якщо його немає.")
        self._factory = service_factory or partial(service_scope, SubjectService)
        self._on_changed = on_changed

        self.subjects_label = label("", wrap=True)
        self.body.addWidget(self.subjects_label)

        row = QHBoxLayout()
        row.setSpacing(8)
        self.subject_edit = QLineEdit()
        self.subject_edit.setPlaceholderText("Назва предмета, напр. Астрономія")
        self.subject_edit.setMaxLength(MAX_SUBJECT_NAME)
        self.subject_edit.returnPressed.connect(self._on_add)
        add = button("Додати", variant="primary")
        add.clicked.connect(self._on_add)
        row.addWidget(self.subject_edit, 1)
        row.addWidget(add)
        self.body.addLayout(row)
        self.add_feedback()
        self.load()

    def load(self) -> None:
        try:
            with self._factory() as service:
                subjects = service.list_subjects()
        except Exception:
            logging.exception("Не вдалося завантажити предмети")
            self.subjects_label.setText("Не вдалося завантажити список предметів")
            return
        self.subjects_label.setText(" · ".join(s.name for s in subjects))

    def _on_add(self) -> None:
        try:
            with self._factory() as service:
                service.add_subject(self.subject_edit.text())
        except SubjectError as error:
            self.show_error(str(error))
            return
        except Exception:
            logging.exception("Не вдалося додати предмет")
            self.show_error(GENERIC_ERROR)
            return
        self.error.hide()
        self.subject_edit.clear()
        self.load()
        if self._on_changed is not None:
            self._on_changed()


# ---------------------------------------------------------------- резервні копії (етап 7a)

BACKUP_DIR_KEY = "backup_dir"
NO_BACKUPS_TEXT = "Копій ще немає"
FALLBACK_NOTE = "Обрана папка недоступна — копії зберігаються в типовій"


def load_backup_dir() -> str | None:
    """Обрана викладачкою папка копій (QSettings) або None — тоді типова."""
    value = app_settings().value(BACKUP_DIR_KEY, "")
    return str(value) if value else None


def save_backup_dir(path: str | None) -> None:
    settings = app_settings()
    if path:
        settings.setValue(BACKUP_DIR_KEY, path)
    else:
        settings.remove(BACKUP_DIR_KEY)


def _default_backup_service(backup_dir: str | None):
    from journal.services.backup_service import BackupService

    return BackupService.for_app(backup_dir)


def open_folder(path: Path) -> None:
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))


class BackupsCard(SettingsCard):
    """Резервні копії: створити зараз, відкрити/змінити папку, відновити з копії."""

    def __init__(
        self,
        service_factory: Callable[[str | None], object] | None = None,
        get_dir: Callable[[], str | None] = load_backup_dir,
        set_dir: Callable[[str | None], None] = save_backup_dir,
        on_restored: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(
            "Резервні копії",
            "Копія робиться автоматично при закритті програми. Можна зберігати її на флешці "
            "або в папці, що синхронізується з хмарою.",
            wrap_hint=True,
        )
        self._factory = service_factory or _default_backup_service
        self._get_dir = get_dir
        self._set_dir = set_dir
        self._on_restored = on_restored or QApplication.quit

        self.folder_label = ElidedLabel()
        self.body.addWidget(self.folder_label)
        self.latest_label = label("", muted=True, wrap=True)
        self.body.addWidget(self.latest_label)
        self.fallback_note = label(FALLBACK_NOTE, muted=True, wrap=True)
        self.fallback_note.hide()
        self.body.addWidget(self.fallback_note)

        row = QHBoxLayout()
        row.setSpacing(8)
        self.create_button = button("Створити копію зараз", variant="primary")
        self.create_button.clicked.connect(self._on_create)
        self.open_button = button("Відкрити папку")
        self.open_button.clicked.connect(self._on_open)
        self.change_button = button("Змінити папку…")
        self.change_button.clicked.connect(self._on_change_folder)
        self.restore_button = button("Відновити з копії…")
        self.restore_button.clicked.connect(self._on_restore)
        for widget in (self.create_button, self.open_button, self.change_button, self.restore_button):
            row.addWidget(widget)
        row.addStretch(1)
        self.body.addLayout(row)
        self.add_feedback()
        self.refresh()

    # ---------- допоміжне ----------

    def _service(self):
        return self._factory(self._get_dir())

    def refresh(self) -> None:
        try:
            service = self._service()
            backups = service.list_backups()
            folder = service.effective_dir()
        except Exception:
            log_failure("Не вдалося прочитати список резервних копій")
            self.folder_label.setText("")
            self.latest_label.setText("Не вдалося прочитати список копій")
            self.fallback_note.hide()
            return
        self.folder_label.setText(f"Папка: {folder}")
        self.folder_label.setToolTip(str(folder))
        self.fallback_note.setVisible(bool(getattr(service, "fallback_used", False)))
        if backups:
            newest = backups[0]
            self.latest_label.setText(
                f"Остання копія: {newest.created:%d.%m.%Y %H:%M} ({newest.kind_title})"
            )
        else:
            self.latest_label.setText(NO_BACKUPS_TEXT)

    # ---------- дії ----------

    def _on_create(self) -> None:
        from journal.services.backup_service import BackupError

        try:
            service = self._service()
            path = backup_dialogs.run_busy(
                self, "Створюю резервну копію…", lambda: service.create_backup("manual")
            )
        except BackupError as error:
            self.show_error(str(error))
            return
        except Exception:
            log_failure("Не вдалося створити резервну копію")
            self.show_error("Не вдалося створити резервну копію. Деталі — у журналі.")
            return
        text = f"Копію створено: {path.name}"
        if getattr(service, "fallback_used", False):
            text += f"\n{backup_dialogs.FALLBACK_TEXT}"
        self.show_status(text)
        self.refresh()

    def _on_open(self) -> None:
        try:
            folder = Path(self._service().effective_dir(create=True))
        except Exception:
            log_failure("Не вдалося відкрити папку копій")
            self.show_error("Не вдалося відкрити папку копій.")
            return
        open_folder(folder)

    def _on_change_folder(self) -> None:
        start = self._get_dir() or str(self._service().effective_dir())
        chosen = QFileDialog.getExistingDirectory(self, "Папка для резервних копій", start)
        if not chosen:
            return
        self._set_dir(os.path.normpath(chosen))
        self.show_status("Папку змінено. Нові копії зберігатимуться тут.")
        self.refresh()

    def _on_restore(self) -> None:
        from journal.services.backup_service import BackupError, RestoreFailed

        try:
            service = self._service()
            start = str(service.effective_dir())
        except Exception:
            log_failure("Не вдалося підготувати відновлення")
            self.show_error("Не вдалося підготувати відновлення. Деталі — у журналі.")
            return
        chosen, _ = QFileDialog.getOpenFileName(
            self, "Відновити з копії", start, "Резервні копії (*.dump)"
        )
        if not chosen:
            return
        try:
            info = service.inspect(Path(chosen))
        except BackupError as error:
            self.show_error(str(error))
            return
        except Exception:
            log_failure("Не вдалося перевірити файл копії")
            self.show_error("Не вдалося прочитати файл копії. Деталі — у журналі.")
            return
        if not backup_dialogs.confirm_restore(self, info):
            return
        try:
            backup_dialogs.run_busy(self, "Відновлюю дані…", lambda: service.restore(info.path))
        except RestoreFailed as error:
            self.show_error(str(error))
            backup_dialogs.show_warning(self, "Відновлення не вдалося", str(error))
            self.refresh()
            return
        except BackupError as error:
            self.show_error(str(error))
            return
        except Exception:
            log_failure("Відновлення завершилось несподіваною помилкою")
            self.show_error("Не вдалося відновити дані. Деталі — у журналі.")
            return
        backup_dialogs.show_info(
            self, "Дані відновлено", "Дані відновлено. Програма закриється — відкрийте її знову."
        )
        self._on_restored()


# ---------------------------------------------------------------- обліковий запис (етап 7b)

class AccountCard(SettingsCard):
    """Зміна пароля: поточний + новий + повтор. Після успіху показує новий код відновлення."""

    def __init__(
        self,
        teacher_id: int,
        runner: Callable[[Callable], object] | None = None,
        show_code: Callable[[QWidget | None, str], None] | None = None,
    ) -> None:
        super().__init__(
            "Обліковий запис",
            "Після зміни пароля програма покаже новий код відновлення. Старий код перестане діяти.",
            wrap_hint=True,
        )
        self.teacher_id = teacher_id
        self._runner = runner or auth_dialogs.run_auth_action
        self._show_code = show_code or auth_dialogs.show_recovery_code

        self.current_edit = self._password_edit("Поточний пароль")
        self.new_edit = self._password_edit("Новий пароль (щонайменше 8 символів)")
        self.repeat_edit = self._password_edit("Новий пароль ще раз")
        for edit in (self.current_edit, self.new_edit, self.repeat_edit):
            self.body.addWidget(edit)

        actions = QHBoxLayout()
        self.change_button = button("Змінити пароль", variant="primary")
        self.change_button.clicked.connect(self._on_change)
        actions.addWidget(self.change_button)
        actions.addStretch(1)
        self.body.addLayout(actions)
        self.add_feedback()

    @staticmethod
    def _password_edit(placeholder: str) -> QLineEdit:
        edit = QLineEdit()
        edit.setPlaceholderText(placeholder)
        edit.setEchoMode(QLineEdit.EchoMode.Password)
        return edit

    def _on_change(self) -> None:
        current, new = self.current_edit.text(), self.new_edit.text()
        if new != self.repeat_edit.text():
            self.show_error("Нові паролі не збігаються")
            return
        try:
            code = self._runner(lambda auth: auth.change_password(self.teacher_id, current, new))
        except AuthError as error:
            self.show_error(str(error))
            self.current_edit.clear()
            return
        except Exception:
            logging.exception("Не вдалося змінити пароль")
            self.show_error(GENERIC_ERROR)
            return
        for edit in (self.current_edit, self.new_edit, self.repeat_edit):
            edit.clear()
        self.show_status("Пароль змінено.")
        self._show_code(self, code)
