"""Головне вікно: бічна панель з навігацією зліва, сторінки справа."""
from collections.abc import Callable

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from journal.services.auth_service import CurrentUser
from journal.version import app_version
from journal.ui import icons, theme
from journal.ui.classes_page import ClassesPage
from journal.ui.journals_page import JournalsPage
from journal.ui.settings_cards import AccountCard, BackupsCard, SemestersCard, SubjectsCard
from journal.ui.widgets import brand_mark, button, card, label, segment_button

# (іконка, підпис у меню)
NAV_ITEMS = [("users", "Класи"), ("book", "Журнали"), ("settings", "Налаштування")]
THEME_CHOICES = [("light", "Світла", "sun"), ("dark", "Темна", "moon")]


def initials(full_name: str) -> str:
    """«Олена Іванівна Коваль» → «ОІ»."""
    parts = full_name.split()
    return "".join(p[0] for p in parts[:2]).upper() or "?"


class MainWindow(QMainWindow):
    def __init__(
        self,
        current_user: CurrentUser,
        exit_backup: Callable[[QWidget], None] | None = None,
    ) -> None:
        super().__init__()
        self.current_user = current_user
        # Автокопія при закритті (етап 7a): передає app.py; у тестах за замовчуванням її немає.
        self._exit_backup = exit_backup
        self._exit_backup_done = False
        self.setWindowTitle(f"Електронний журнал {app_version()} — {current_user.full_name}")
        self.setMinimumSize(1100, 700)

        # Іконки малюються кольором поточної теми, тож при зміні теми їх треба перемалювати.
        self._icon_refreshers: list[Callable[[], None]] = []

        self.pages = QStackedWidget()
        self.classes_page = ClassesPage(current_user)
        self.pages.addWidget(self.classes_page)
        self.journals_page = JournalsPage(current_user)
        self.pages.addWidget(self.journals_page)
        self.pages.addWidget(self._build_settings_page())

        content = QWidget()
        content.setObjectName("Content")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(40, 32, 40, 32)
        content_layout.addWidget(self.pages)

        central = QWidget()
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._build_sidebar())
        layout.addWidget(content, 1)
        self.setCentralWidget(central)

        quit_action = QAction("Вийти", self)
        quit_action.setShortcut(QKeySequence("Ctrl+Q"))
        quit_action.triggered.connect(self.close)
        self.addAction(quit_action)

        self._refresh_icons()

    # ---------- Бічна панель ----------

    def _build_sidebar(self) -> QFrame:
        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(250)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(16, 20, 16, 16)
        layout.setSpacing(4)

        # Логотип і назва
        mark = brand_mark(36)
        self._icon_refreshers.append(
            lambda: mark.setPixmap(icons.pixmap("cap", theme.color("accent_text"), size=20))
        )
        titles = QVBoxLayout()
        titles.setSpacing(0)
        titles.addWidget(label("Електронний журнал", object_name="Brand"))
        brand = QHBoxLayout()
        brand.setSpacing(10)
        brand.addWidget(mark)
        brand.addLayout(titles, 1)
        layout.addLayout(brand)
        layout.addSpacing(24)

        # Навігація
        self.nav = QListWidget()
        self.nav.setObjectName("Nav")
        self.nav.setIconSize(QSize(18, 18))
        self.nav.setCursor(Qt.CursorShape.PointingHandCursor)
        for icon_name, text in NAV_ITEMS:
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, icon_name)
            self.nav.addItem(item)
        self.nav.currentRowChanged.connect(self._on_nav_changed)
        self.nav.setCurrentRow(0)
        self._icon_refreshers.append(self._refresh_nav_icons)
        layout.addWidget(self.nav, 1)

        # Користувач унизу
        divider = QFrame()
        divider.setObjectName("Divider")
        divider.setFixedHeight(1)
        layout.addWidget(divider)
        layout.addSpacing(8)

        avatar = QLabel(initials(self.current_user.full_name))
        avatar.setObjectName("Avatar")
        avatar.setFixedSize(36, 36)
        avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        who = QVBoxLayout()
        who.setSpacing(0)
        name = label(self.current_user.full_name)
        name.setToolTip(self.current_user.full_name)
        who.addWidget(name)
        who.addWidget(label(f"@{self.current_user.username}", muted=True))
        user_row = QHBoxLayout()
        user_row.setSpacing(10)
        user_row.addWidget(avatar)
        user_row.addLayout(who, 1)
        layout.addLayout(user_row)
        layout.addSpacing(4)

        logout = button("Вийти", variant="ghost")
        logout.setToolTip("Закрити застосунок (Ctrl+Q)")
        logout.clicked.connect(self.close)
        self._icon_refreshers.append(
            lambda: logout.setIcon(icons.icon("logout", theme.color("muted"), size=16))
        )
        layout.addWidget(logout)
        return sidebar

    def _on_nav_changed(self, row: int) -> None:
        """Перемикає сторінку; журнали оновлюються, бо на сторінці «Класи» могли щось змінити."""
        self.pages.setCurrentIndex(row)
        if self.pages.currentWidget() is getattr(self, "journals_page", None):
            self.journals_page.refresh()

    def _refresh_nav_icons(self) -> None:
        for row in range(self.nav.count()):
            item = self.nav.item(row)
            name = item.data(Qt.ItemDataRole.UserRole)
            item.setIcon(icons.icon(name, theme.color("muted"), theme.color("accent"), size=18))

    # ---------- Сторінки ----------

    def _page(self, title: str, subtitle: str) -> tuple[QWidget, QVBoxLayout]:
        """Сторінка з великим заголовком і підзаголовком."""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addWidget(label(title, object_name="PageTitle"))
        layout.addWidget(label(subtitle, muted=True))
        layout.addSpacing(24)
        return page, layout

    def _build_settings_page(self) -> QWidget:
        page, layout = self._page("Налаштування", "Вигляд застосунку, семестри, довідник предметів, обліковий запис і резервні копії.")

        # Заголовок і підзаголовок нерухомі; три картки прокручуються, щоб помилки
        # й списки конфліктів не стискали поля.
        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(16)

        frame, card_layout = card()
        card_layout.addWidget(label("Оформлення", object_name="CardTitle"))
        card_layout.addWidget(label("Тема зберігається між запусками.", muted=True))
        card_layout.addSpacing(6)

        self.theme_group = QButtonGroup(self)
        row = QHBoxLayout()
        row.setSpacing(8)
        active = theme.current_theme()
        for name, title, icon_name in THEME_CHOICES:
            btn = segment_button(title, reserve_bold=False)
            btn.setChecked(name == active)
            btn.setProperty("themeName", name)
            self._icon_refreshers.append(
                lambda b=btn, i=icon_name: b.setIcon(
                    icons.icon(i, theme.color("accent" if b.isChecked() else "muted"), size=16)
                )
            )
            self.theme_group.addButton(btn)
            row.addWidget(btn)
        row.addStretch(1)
        # Сигнал підключаємо після початкового вибору, щоб не перезаписувати налаштування.
        self.theme_group.buttonClicked.connect(self._on_theme_clicked)
        card_layout.addLayout(row)

        body_layout.addWidget(frame)
        self.semesters_card = SemestersCard(
            self.current_user.id, on_saved=lambda: self.journals_page.refresh()
        )
        body_layout.addWidget(self.semesters_card)
        self.subjects_card = SubjectsCard(on_changed=lambda: self.journals_page.refresh())
        body_layout.addWidget(self.subjects_card)
        self.account_card = AccountCard(self.current_user.id)
        body_layout.addWidget(self.account_card)
        self.backups_card = BackupsCard(on_restored=self._close_after_restore)
        body_layout.addWidget(self.backups_card)
        body_layout.addStretch(1)

        self.settings_scroll = QScrollArea()
        self.settings_scroll.setWidgetResizable(True)
        self.settings_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.settings_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.settings_scroll.setWidget(body)
        layout.addWidget(self.settings_scroll, 1)
        return page

    # ---------- Закриття та резервні копії ----------

    def _close_after_restore(self) -> None:
        """Після відновлення з копії програма закривається без автокопії (дані щойно замінено)."""
        self._exit_backup_done = True
        self.close()

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt API)
        if self._exit_backup is not None and not self._exit_backup_done:
            self._exit_backup_done = True
            try:
                self._exit_backup(self)
            except Exception:  # noqa: BLE001 — програма ніколи не мусить «застрягти» на виході
                from journal.logging_setup import log_failure

                log_failure("Помилка автоматичної копії при виході")
        super().closeEvent(event)

    # ---------- Тема ----------

    def _on_theme_clicked(self, btn) -> None:
        name = btn.property("themeName")
        theme.apply_theme(QApplication.instance(), name)
        theme.save_theme_name(name)
        self._refresh_icons()

    def _refresh_icons(self) -> None:
        for refresh in self._icon_refreshers:
            refresh()
        self.classes_page.refresh_icons()
        self.journals_page.refresh_icons()
