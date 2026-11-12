"""QA: перевірка вигляду застосунку скриншотами (offscreen, тестова база, одна транзакція з відкатом).

Запуск:  .venv\\Scripts\\python.exe scripts\\qa\\screens.py
Результат: docs/screenshots/qa/NN_екран_стан_{light|dark}.png і JSON з автоматичними перевірками
(шлях задається змінною QA_OUT, за замовчуванням docs/screenshots/qa/_checks.json не створюється — друк у stdout).

Правила: лише TEST_DATABASE_URL (ім'я бази закінчується на _test); усе в одній зовнішній транзакції,
яка відкочується; вигадані імена; модальні вікна підмінені, тому нічого не блокується.
"""
import faulthandler
import json
import os
import random
import re
import sys
from contextlib import contextmanager
from datetime import date, timedelta
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.stdout.reconfigure(encoding="utf-8")
faulthandler.dump_traceback_later(840, exit=True)  # страховка від зависання

from PySide6.QtCore import QPoint, Qt, QTimer  # noqa: E402
from PySide6.QtGui import QContextMenuEvent, QPainter  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QWidget,
)
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from journal import db  # noqa: E402
from journal.config import get_test_database_url  # noqa: E402
from journal.models import Teacher  # noqa: E402
from journal.services.auth_service import CurrentUser  # noqa: E402
from journal.services.class_service import ClassService  # noqa: E402
from journal.services.journal_service import JournalService  # noqa: E402
from journal.services.rollover_service import RolloverService  # noqa: E402
from journal.services.subject_service import SubjectService  # noqa: E402
from journal.ui import theme  # noqa: E402
from journal.ui.auth_dialogs import LoginDialog, RegisterDialog  # noqa: E402
from journal.ui.class_dialogs import ClassDialog, ImportStudentsDialog, StudentDialog  # noqa: E402
from journal.ui.journal_dialogs import (  # noqa: E402
    DeleteJournalDialog,
    DeleteLessonDialog,
    JournalSettingsDialog,
    LessonDialog,
    NewJournalDialog,
)
from journal.ui.journals_page import default_api_factory  # noqa: E402
from journal.ui.main_window import MainWindow  # noqa: E402
from journal.ui.rollover_dialog import RolloverDialog  # noqa: E402

OUT_DIR = ROOT / "docs" / "screenshots" / "qa"
THEMES = ("light", "dark")
YEAR = "2026-2027"

# ---------------------------------------------------------------------------
# База: лише тестова, одна транзакція з відкатом
# ---------------------------------------------------------------------------

url = get_test_database_url()
assert (make_url(url).database or "").endswith("_test"), "База не тестова — зупиняємось"
engine = create_engine(url, hide_parameters=True)
db.init_engine(url)  # про всяк випадок: будь-який «забутий» session_scope теж іде в тестову базу
connection = engine.connect()
outer = connection.begin()


@contextmanager
def fake_scope():
    """Те саме, що journal.db.session_scope, але всередині зовнішньої транзакції (SAVEPOINT)."""
    with Session(bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False) as s, s.begin():
        yield s


import journal.ui.main_window  # noqa: E402,F401  (щоб усі модулі були в sys.modules)

db.session_scope = fake_scope
for _name, _mod in list(sys.modules.items()):
    if _name.startswith("journal.") and hasattr(_mod, "session_scope"):
        _mod.session_scope = fake_scope

# ---------------------------------------------------------------------------
# Qt: застосунок і підміна модальних вікон
# ---------------------------------------------------------------------------

app = QApplication.instance() or QApplication(sys.argv)
LAST = {"box": None, "menu": None}


def _fake_dialog_exec(self, *args):
    self.show()
    app.processEvents()
    LAST["box"] = self
    return 0


def _fake_message(kind):
    def fn(parent, title, text, *a, **k):
        box = QMessageBox(kind, title, text, parent=parent)
        box.show()
        LAST["box"] = box
        return QMessageBox.StandardButton.Ok

    return staticmethod(fn)


QDialog.exec = _fake_dialog_exec
QMessageBox.exec = _fake_dialog_exec
QMessageBox.warning = _fake_message(QMessageBox.Icon.Warning)
QMessageBox.information = _fake_message(QMessageBox.Icon.Information)

# ---------------------------------------------------------------------------
# Знімки та автоматичні перевірки
# ---------------------------------------------------------------------------

OUT_DIR.mkdir(parents=True, exist_ok=True)
for old in OUT_DIR.glob("*.png"):
    old.unlink()

counter = [0]
SHOTS: list[str] = []
CLIPPED: list[dict] = []
SIZE_NOTES: list[dict] = []


def settle(n: int = 3) -> None:
    for _ in range(n):
        app.processEvents()
        QTest.qWait(30)


def close_popups() -> None:
    while (p := app.activePopupWidget()) is not None:
        p.close()
        app.processEvents()
    menu = LAST["menu"]
    if menu is not None:
        menu.hide()
        LAST["menu"] = None


def compose(base: QWidget, popups: list):
    """Знімок вікна з намальованими поверх нього спливними вікнами: список (QPixmap, позиція у вікні).
    (Екран offscreen має 800x600, тому справжня позиція спливних вікон спотворена — малюємо де треба.)"""
    pixmap = base.grab()
    if popups:
        painter = QPainter(pixmap)
        for pm, pos in popups:
            painter.drawPixmap(pos, pm)
        painter.end()
    return pixmap


def check_widgets(root: QWidget, tag: str) -> None:
    """Видимі підписи/кнопки/поля, текст яких не вміщається у свій прямокутник."""
    for w in root.findChildren(QWidget):
        if not w.isVisible():
            continue
        problem = None
        if isinstance(w, QLabel):
            text = w.text()
            if text and w.textFormat() != Qt.TextFormat.RichText:
                fm = w.fontMetrics()
                rect = w.contentsRect()
                if w.wordWrap():
                    need = w.heightForWidth(w.width())
                    if need > w.height() + 1:
                        problem = ("wrap-height", need, w.height())
                else:
                    need = max(fm.horizontalAdvance(line) for line in text.split("\n"))
                    if need > rect.width() + 1:
                        problem = ("width", need, rect.width())
                    elif fm.lineSpacing() * (text.count("\n") + 1) > rect.height() + 2:
                        problem = ("height", fm.lineSpacing() * (text.count("\n") + 1), rect.height())
        elif isinstance(w, (QPushButton, QCheckBox)):
            hint = w.sizeHint()
            if hint.width() > w.width() + 1:
                problem = ("sizeHint-width", hint.width(), w.width())
            elif hint.height() > w.height() + 1:
                problem = ("sizeHint-height", hint.height(), w.height())
        elif isinstance(w, QComboBox):
            need = w.fontMetrics().horizontalAdvance(w.currentText()) + 26 + 20
            if need > w.width() + 1:
                problem = ("combo-text", need, w.width())
        elif isinstance(w, QLineEdit):
            need = w.fontMetrics().horizontalAdvance(w.text()) + 20
            if w.text() and need > w.width() + 1:
                problem = ("lineedit-text", need, w.width())
        if problem is None and isinstance(w, (QLabel, QPushButton, QCheckBox, QComboBox, QLineEdit)):
            parent = w.parentWidget()
            geo = w.geometry()
            if parent is not None and (geo.right() > parent.width() + 1 or geo.left() < -1):
                problem = ("outside-parent", geo.right(), parent.width())
        if problem:
            label = ""
            if isinstance(w, (QLabel, QPushButton, QCheckBox)):
                label = w.text()
            elif isinstance(w, QComboBox):
                label = w.currentText()
            elif isinstance(w, QLineEdit):
                label = w.text()
            CLIPPED.append(
                {
                    "tag": tag,
                    "widget": type(w).__name__,
                    "object": w.objectName(),
                    "text": label[:60],
                    "kind": problem[0],
                    "need": problem[1],
                    "have": problem[2],
                }
            )


def state(name, build, *, size=(1280, 800), themes=THEMES, post=None):
    """Будує віджет для кожної теми, показує, знімає PNG і перевіряє обрізання."""
    counter[0] += 1
    number = counter[0]
    for th in themes:
        theme.apply_theme(app, th)
        widget = build()
        if isinstance(widget, QMainWindow) and size:
            widget.resize(*size)
        widget.show()
        widget.activateWindow()
        settle()
        popups = []
        if post is not None:
            popups = post(widget) or []
            settle()
        tag = f"{number:02d}_{name}_{th}"
        compose(widget, popups).save(str(OUT_DIR / f"{tag}.png"))
        SHOTS.append(tag)
        if isinstance(widget, QMainWindow) and size and (widget.width(), widget.height()) != tuple(size):
            SIZE_NOTES.append({"tag": tag, "asked": list(size), "got": [widget.width(), widget.height()]})
        check_widgets(widget, tag)
        close_popups()
        widget.close()
        widget.deleteLater()
        settle(1)
    print(f"{number:02d} {name}", flush=True)


# ---------------------------------------------------------------------------
# Вигадані дані
# ---------------------------------------------------------------------------

NAMES = [
    "Демченко Олена", "Тестовий Іван", "Прикладний Максим", "Зразкова Марія", "Вигаданий Андрій",
    "Умовна Софія", "Демо Богдан", "Тестова Анна", "Прикладна Катерина", "Зразковий Олег",
    "Вигадана Юлія", "Умовний Денис", "Демченко Артем", "Тестовий Назар", "Прикладний Тимур",
    "Зразкова Дарина", "Вигаданий Роман", "Умовна Поліна", "Демо Станіслав", "Тестова Вікторія",
    "Прикладна Ірина", "Зразковий Павло", "Вигадана Оксана", "Умовний Святослав", "Демченко Христина",
    "Тестовий Ярослав", "Прикладний Георгій", "Зразкова Аліна", "Вигаданий Матвій", "Умовна Злата",
    "Демо Єва", "Тестова Галина", "Прикладна Ївга", "Зразковий Юрій", "Вигаданий Ілля", "Умовна Євгенія",
]
TOPICS = [
    "Повторення: дії зі звичайними дробами", "Лінійні рівняння з одним невідомим", "Системи лінійних рівнянь",
    "Функція та її графік", "Квадратні рівняння", "Теорема Вієта", "Нерівності з однією змінною",
    "Арифметична прогресія", "Геометрична прогресія", "Степінь із цілим показником", "Раціональні вирази",
    "Подібність трикутників", "Теорема Піфагора", "Розв'язування задач", "Тригонометричні функції",
]
LONG_TOPIC = (
    "Узагальнення й систематизація знань з теми «Функції та їхні графіки»: область визначення, множина значень, "
    "нулі функції, проміжки знакосталості, зростання та спадання, парність і непарність, перетворення графіків "
    "функцій та розв'язування прикладних задач на побудову й дослідження"
)[:255]
LONG_STUDENT = " ".join(["Вигаданопрізвищенко-Тестовопрізвищенко"] * 8)[:150].rstrip()
LONG_CLASS = "9-Б фізико-математичний ліцей"[:20]
LONG_SUBJECT = "Інтегрований курс математики та фізики для ліцеїв та гімназій"[:50].rstrip()
EXTRA_SUBJECTS = [
    "Хімія", "Біологія", "Географія", "Історія України", "Всесвітня історія", "Українська мова",
    "Українська література", "Англійська мова", "Інформатика", "Фізична культура", "Мистецтво",
    "Основи здоров'я", "Природознавство", "Захист України", "Громадянська освіта", "Астрономія", "Трудове навчання",
]

sess = Session(bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False)
cs, js, ss = ClassService(sess), JournalService(sess), SubjectService(sess)
SUBJECT = {s.name: s.id for s in ss.list_subjects()}
_teacher_no = [0]


def make_teacher(full_name: str) -> CurrentUser:
    _teacher_no[0] += 1
    teacher = Teacher(username=f"qa_demo_{_teacher_no[0]}", password_hash="x", full_name=full_name)
    sess.add(teacher)
    sess.flush()
    return CurrentUser(teacher.id, teacher.username, teacher.full_name)


def make_class(user, name, students=0, offset=0, year=YEAR):
    info = cs.create_class(user.id, name, year)
    if students:
        cs.import_students(user.id, info.id, "\n".join(NAMES[(offset + i) % len(NAMES)] for i in range(students)))
    sess.flush()
    return info


def make_journal(user, class_id, subject):
    return js.create_journal(user.id, class_id, SUBJECT[subject])


def lesson_dates(start: date, count: int, weekdays=(0, 2, 4)) -> list[date]:
    out, day = [], start
    while len(out) < count:
        if day.weekday() in weekdays:
            out.append(day)
        day += timedelta(days=1)
    return out


def add_lessons(user, journal_id, dates, plan=None):
    """plan: {індекс: (тип, тема)}; решта — звичайні уроки з темами по колу."""
    plan = plan or {}
    lessons = []
    for i, d in enumerate(dates):
        kind, topic = plan.get(i, ("regular", TOPICS[i % len(TOPICS)]))
        lessons.append(js.create_lesson(user.id, journal_id, d, kind, topic))
    return lessons


def fill_marks(user, class_id, lessons, seed=7):
    rng = random.Random(seed)
    students = [s for s in cs.list_students(user.id, class_id) if not s.archived]
    top_left = {  # передбачувані перші клітинки: усі види позначок
        (0, 0): ("present", 5, "Демо-коментар"), (0, 1): ("absent", None, None), (0, 2): ("sick", None, None),
        (0, 3): ("late", None, None), (0, 4): ("late", 9, None), (0, 5): ("present", 12, None),
        (0, 6): ("present", 11, None), (0, 7): ("present", 10, None), (1, 0): ("present", 1, None),
        (1, 1): ("present", 2, None), (1, 2): ("present", 3, None), (1, 3): ("present", 4, None),
        (1, 4): ("present", 6, None), (1, 5): ("present", 7, None), (1, 6): ("present", 8, None),
    }
    for r, student in enumerate(students):
        for c, lesson in enumerate(lessons):
            if (r, c) in top_left:
                att, grade, comment = top_left[(r, c)]
            else:
                x = rng.random()
                if x < 0.12:
                    continue
                if x < 0.20:
                    att, grade = "absent", None
                elif x < 0.24:
                    att, grade = "sick", None
                elif x < 0.28:
                    att, grade = "late", None
                elif x < 0.31:
                    att, grade = "late", rng.randint(5, 12)
                else:
                    att, grade = "present", rng.choice([3, 5, 6, 7, 7, 8, 8, 9, 9, 10, 10, 11, 12, 4, 2, 1])
                comment = None
            js.set_cell(user.id, lesson.id, student.id, att, grade, comment)
    sess.flush()


def grid_lessons(user, journal_id, semester=1):
    return js.get_grid(user.id, journal_id, semester).lessons


def journal_info(user, journal_id):
    return next(j for j in js.list_journals(user.id, True) if j.id == journal_id)


def window(user, row=0):
    w = MainWindow(user)
    w.nav.setCurrentRow(row)
    return w


def open_journal(w, journal_id):
    w.nav.setCurrentRow(1)
    w.journals_page.open_journal(journal_id)
    return w


def popup_of_combo(w, combo):
    combo.showPopup()
    settle()
    popup = app.activePopupWidget() or combo.view().window()
    return [(popup.grab(), combo.mapTo(w, QPoint(0, combo.height())))]


print("Дані: створюємо вигадані класи, журнали, оцінки...", flush=True)
T = make_teacher("Демо Викладач")
T_EMPTY = make_teacher("Порожній Викладач")

c5 = make_class(T, "5-А", 12, 0)
c6 = make_class(T, "6-Б", 20, 4)  # без журналів: тут видалення класу
c7 = make_class(T, "7-А")  # без учнів
c8 = make_class(T, "8-А", 5, 9)  # журнал без уроків
c9 = make_class(T, "9-А", 31, 0)
c11 = make_class(T, "11-А", 28, 3)
c10 = make_class(T, "10-Б", 24, 6)  # потім в архів

j5 = make_journal(T, c5.id, "Математика")
j7 = make_journal(T, c7.id, "Фізика")
j8 = make_journal(T, c8.id, "Математика")
j9m = make_journal(T, c9.id, "Математика")
j9f = make_journal(T, c9.id, "Фізика")
j11 = make_journal(T, c11.id, "Геометрія") if "Геометрія" in SUBJECT else make_journal(T, c11.id, "Алгебра")
j10 = make_journal(T, c10.id, "Алгебра")

add_lessons(T, j5.id, lesson_dates(date(2026, 9, 1), 3))
add_lessons(T, j11.id, lesson_dates(date(2026, 9, 1), 2))
add_lessons(T, j9f.id, lesson_dates(date(2026, 9, 2), 6, (1, 3)))
plan9 = {
    1: ("regular", None), 2: ("regular", LONG_TOPIC), 3: ("regular", "Довга, але ще помірна тема уроку про системи рівнянь з двома змінними"),
    4: ("test", "Лінійні рівняння"), 5: ("regular", None), 8: ("lab", "Практична робота: графіки функцій"),
    12: ("independent", "Квадратні рівняння"), 13: ("test", None),
}
lessons9 = add_lessons(T, j9m.id, lesson_dates(date(2026, 9, 1), 25), plan9)
fill_marks(T, c9.id, lessons9)
add_lessons(T, j9m.id, [date(2027, 1, 13), date(2027, 1, 15), date(2027, 1, 18), date(2027, 1, 20)])
# вибулий учень з оцінками: останній за номером
students9 = [s for s in cs.list_students(T.id, c9.id) if not s.archived]
withdrawn9 = students9[-1]
cs.set_student_archived(T.id, withdrawn9.id, True)
# 11-А: двоє вибулих
st11 = cs.list_students(T.id, c11.id)
cs.set_student_archived(T.id, st11[4].id, True)
cs.set_student_archived(T.id, st11[11].id, True)
# 10-Б: архівний журнал з уроками у листопаді й грудні
dates10 = lesson_dates(date(2026, 9, 1), 8) + [date(2026, 11, 4), date(2026, 12, 9)]
lessons10 = add_lessons(T, j10.id, dates10)
fill_marks(T, c10.id, lessons10, seed=3)
cs.set_class_archived(T.id, c10.id, True)
sess.flush()

# вчителька з конфліктами меж семестрів (грудневі уроки)
T_CONF = make_teacher("Конфліктна Викладачка")
cc = make_class(T_CONF, "9-А", 6)
jc = make_journal(T_CONF, cc.id, "Математика")
add_lessons(T_CONF, jc.id, lesson_dates(date(2026, 9, 1), 4) + [date(2026, 12, 2), date(2026, 12, 9), date(2026, 12, 16)])

# вчителі для переходу на новий рік
T_R1 = make_teacher("Перехід Один")
r1 = make_class(T_R1, "9-А", 28)
make_journal(T_R1, r1.id, "Математика")
make_journal(T_R1, r1.id, "Фізика")

T_R8 = make_teacher("Перехід Вісім")
for name, n, subj in (
    ("5-А", 24, "Математика"), ("6-А", 22, None), ("8-А", 26, "Фізика"), ("9-А", 28, "Алгебра"),
    ("9-Б", 25, "Математика"), ("10-А", 20, "Фізика"), ("11-Б", 27, "Алгебра"), ("Гурток", 10, None),
):
    ci = make_class(T_R8, name, n)
    if subj:
        make_journal(T_R8, ci.id, subj)
make_class(T_R8, "10-Б", 3, year="2027-2028")  # 9-Б → 10-Б уже існує

T_R0 = make_teacher("Перехід Без Журналів")
make_class(T_R0, "7-А", 18)

T_RL = make_teacher("Перехід Довгі Назви")
rl1 = make_class(T_RL, LONG_CLASS, 12)
make_journal(T_RL, rl1.id, "Математика")
make_class(T_RL, ("9-В фізико-математичний ліцей")[:19].rstrip(), 14)

PLAN_DATE = date(2027, 8, 1)


def plan_for(user):
    return RolloverService(sess).plan(user.id, PLAN_DATE)


# ---------------------------------------------------------------------------
# Знімки
# ---------------------------------------------------------------------------

# 1. Вхід і реєстрація (з помилкою)
def build_login_error():
    d = LoginDialog()
    d.username_edit.setText("demo_user")
    d.password_edit.setText("z" * 9)
    d._on_login()
    return d


def build_register_error():
    d = RegisterDialog()
    d.full_name_edit.setText("Демо Викладач")
    d.username_edit.setText("demo_teacher")
    d.password_edit.setText("a" * 9)
    d.repeat_edit.setText("b" * 9)
    d._on_create()
    return d


state("login_error", build_login_error, size=None)
state("register_error", build_register_error, size=None)

# 2. Список класів
state("classes_empty", lambda: window(T_EMPTY, 0))
state("classes_six", lambda: window(T, 0))
state("classes_six_min", lambda: window(T, 0), size=(1100, 700), themes=("light",))


def build_classes_archived():
    w = window(T, 0)
    w.classes_page.archived_check.setChecked(True)
    return w


state("classes_archived_shown", build_classes_archived)

# 3. Деталі класу
def class_detail(class_id):
    def build():
        w = window(T, 0)
        w.classes_page.open_class(class_id)
        return w

    return build


state("class_no_students", class_detail(c7.id))
state("class_30_students", class_detail(c9.id))
state("class_30_students_min", class_detail(c9.id), size=(1100, 700), themes=("light",))
def build_class_withdrawn():
    w = class_detail(c11.id)()
    table = w.classes_page.table
    table.verticalScrollBar().setValue(table.verticalScrollBar().maximum())
    table.selectRow(table.rowCount() - 1)  # вибулий учень: кнопка стає «Повернути»
    return w


state("class_withdrawn", build_class_withdrawn)
state("class_archived_restore", class_detail(c10.id))

# 4. Діалоги класів
state("class_dialog_new", lambda: ClassDialog(T.id), size=None)


def build_student_dup():
    d = StudentDialog(T.id, c9.id)
    d.name_edit.setText(NAMES[0])
    d._on_add()
    return d


state("student_dup_error", build_student_dup, size=None)


def build_import_preview():
    d = ImportStudentsDialog(T.id, c5.id)
    d.text_edit.setPlainText(f"1. {NAMES[0]}\n2. Новий Учень\n3. Ще Один\n4. Ще Один\n5.   Четвертий   Додатковий")
    d.update_preview()
    return d


state("import_preview", build_import_preview, size=None)


def confirm_from(class_id, action):
    def build():
        w = window(T, 0)
        w.classes_page.open_class(class_id)
        LAST["box"] = None
        getattr(w.classes_page, action)()
        box = LAST["box"]
        box._owner = w  # тримаємо вікно живим
        return box

    return build


state("confirm_archive_class", confirm_from(c9.id, "_on_remove_class"), size=None)
state("confirm_delete_class", confirm_from(c6.id, "_on_remove_class"), size=None)

# довгі імена: клас із 20 символів і учень зі 150
long_class = make_class(T, LONG_CLASS, 3, 20)
cs.add_student(T.id, long_class.id, LONG_STUDENT)
sess.flush()
state("classes_long_name", lambda: window(T, 0))
state("class_long_names", class_detail(long_class.id))

# 5. Список журналів
state("journals_empty", lambda: window(T_EMPTY, 1))
state("journals_cards", lambda: window(T, 1))
state("journals_cards_min", lambda: window(T, 1), size=(1100, 700), themes=("light",))


def build_journals_archived():
    w = window(T, 1)
    w.journals_page.archived_check.setChecked(True)
    return w


state("journals_archived_shown", build_journals_archived)

ss.add_subject(LONG_SUBJECT)
SUBJECT = {s.name: s.id for s in ss.list_subjects()}
jl = make_journal(T, long_class.id, LONG_SUBJECT)
add_lessons(T, jl.id, [date(2026, 9, 15)])
lessons_l = grid_lessons(T, jl.id)
long_students = [s for s in cs.list_students(T.id, long_class.id)]
js.set_cell(T.id, lessons_l[0].id, long_students[0].id, "present", 8, None)
sess.flush()
state("journals_long_subject", lambda: window(T, 1))

# 6. Новий журнал
def build_newjournal_popup():
    return NewJournalDialog(T.id, default_api_factory)


state("newjournal_class_popup", build_newjournal_popup, size=None, post=lambda d: popup_of_combo(d, d.class_combo))
state("newjournal_nothing", lambda: NewJournalDialog(T_EMPTY.id, default_api_factory), size=None)

# 7. Таблиця журналу
def grid(journal_id, **kw):
    def build():
        w = open_journal(window(T, 1), journal_id)
        return w

    return build


state("grid_no_students", grid(j7.id))
state("grid_no_lessons", grid(j8.id))


def build_grid_full():
    w = open_journal(window(T, 1), j9m.id)
    w.journals_page.grid_view.select_cell(2, 3)
    w.journals_page.grid_view.setFocus()
    return w


state("grid_full_selected", build_grid_full)
state("grid_full_selected_min", build_grid_full, size=(1100, 700), themes=("light",))


def post_scroll(w):
    gv = w.journals_page.grid_view
    gv.select_cell(24, 24)
    gv.horizontalScrollBar().setValue(gv.horizontalScrollBar().maximum())
    gv.verticalScrollBar().setValue(gv.verticalScrollBar().maximum())
    settle()
    return []


state("grid_scrolled_right_bottom", build_grid_full, post=post_scroll)


def build_grid_sem2():
    w = open_journal(window(T, 1), j9m.id)
    w.journals_page.semester_buttons[2].click()
    return w


state("grid_semester2", build_grid_sem2)
state("grid_long_names", grid(jl.id))


def build_grid_archived():
    return open_journal(window(T, 1), j10.id)


def post_more_menu(w):
    btn = w.journals_page.menu_btn
    menu = btn.menu()
    print("  «Видалити журнал» enabled:", w.journals_page.delete_journal_action.isEnabled(), flush=True)
    menu.popup(btn.mapToGlobal(QPoint(0, btn.height())))
    settle()
    pm = menu.grab()
    menu.hide()
    return [(pm, btn.mapTo(w, QPoint(btn.width() - pm.width(), btn.height())))]


state("grid_archived_more_menu", build_grid_archived, post=post_more_menu)

# 8. Панель уроків: контекстне меню (справжній шлях через QContextMenuEvent)
def post_panel_menu(w):
    table = w.journals_page.lesson_panel.table
    y = table.rowViewportPosition(3) + 8
    pos = QPoint(60, y)
    got = {}

    def capture():  # меню відкрите справжнім exec() у вкладеному циклі: знімаємо й закриваємо
        menu = app.activePopupWidget()
        if menu is not None:
            got["pm"] = menu.grab()
            menu.close()

    QTimer.singleShot(400, capture)
    event = QContextMenuEvent(QContextMenuEvent.Reason.Mouse, pos, table.viewport().mapToGlobal(pos))
    app.sendEvent(table.viewport(), event)
    settle()
    return [(got["pm"], table.viewport().mapTo(w, pos))] if "pm" in got else []


state("panel_context_menu", build_grid_full, post=post_panel_menu)

# 9. Діалог уроку
l9 = grid_lessons(T, j9m.id)
state("lesson_new", lambda: LessonDialog(T.id, default_api_factory, j9m.id), size=None)
state("lesson_edit_long_topic", lambda: LessonDialog(T.id, default_api_factory, j9m.id, l9[2]), size=None)


def post_calendar(d):
    de = d.date_edit
    QTest.mouseClick(de, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(de.width() - 12, de.height() // 2))
    settle()
    popup = app.activePopupWidget()
    return [(popup.grab(), de.mapTo(d, QPoint(0, de.height())))] if popup is not None else []


state("lesson_calendar_popup", lambda: LessonDialog(T.id, default_api_factory, j9m.id), size=None, post=post_calendar)


def lesson_error(qdate):
    def build():
        from PySide6.QtCore import QDate

        d = LessonDialog(T.id, default_api_factory, j9m.id)
        d.date_edit.setDate(QDate(*qdate))
        d._on_submit()
        return d

    return build


state("lesson_vacation_error", lesson_error((2026, 7, 15)), size=None)
state("lesson_outside_year_error", lesson_error((2025, 10, 14)), size=None)

# 10. Видалення уроку й журналу
state("delete_lesson_typed", lambda: DeleteLessonDialog(l9[0]), size=None)


def build_delete_journal_typed():
    d = DeleteJournalDialog(journal_info(T, j9m.id), 29)
    d.confirm_edit.setText("видалити")
    return d


state("delete_journal_typed_filled", build_delete_journal_typed, size=None)


def build_delete_lesson_simple():
    w = open_journal(window(T, 1), j9m.id)
    page = w.journals_page
    page.semester_buttons[2].click()
    LAST["box"] = None
    page._on_delete_lesson(page.grid_view.grid_model.lessons[0].id)
    box = LAST["box"]
    box._owner = w
    return box


state("delete_lesson_simple_confirm", build_delete_lesson_simple, size=None)


def build_delete_journal_simple():
    w = open_journal(window(T, 1), j8.id)
    LAST["box"] = None
    w.journals_page._on_delete_journal()
    box = LAST["box"]
    box._owner = w
    return box


state("delete_journal_simple_confirm", build_delete_journal_simple, size=None)

# 11. Налаштування
for subject_name in EXTRA_SUBJECTS:
    ss.add_subject(subject_name)
sess.flush()
state("settings_default", lambda: window(T, 2))
state("settings_default_min", lambda: window(T, 2), size=(1100, 700), themes=("light",))


def build_settings_popup():
    return window(T, 2)


state("settings_month_popup", build_settings_popup, post=lambda w: popup_of_combo(w, w.semesters_card.s1_start))


def build_settings_validation():
    w = window(T, 2)
    w.semesters_card.s1_start.setCurrentIndex(0)  # січень
    w.semesters_card._on_save()
    return w


state("settings_validation_error", build_settings_validation)


def build_settings_saved_dup():
    w = window(T, 2)
    w.semesters_card._on_save()
    w.subjects_card.subject_edit.setText("Математика")
    w.subjects_card._on_add()
    return w


state("settings_saved_and_duplicate_subject", build_settings_saved_dup)


def build_settings_conflict(user):
    def build():
        w = window(user, 2)
        card = w.semesters_card
        card.s1_end.setCurrentIndex(card.s1_end.findData(11))  # листопад: грудневі уроки потрапляють у канікули
        card._on_save()
        return w

    return build


state("settings_conflict_3_lessons", build_settings_conflict(T_CONF))
add_lessons(
    T_CONF, make_journal(T_CONF, cc.id, "Фізика").id,
    [date(2026, 12, d) for d in (1, 3, 4, 7, 8, 10, 11, 14, 15, 17)],
)
sess.flush()
state("settings_conflict_13_lessons", build_settings_conflict(T_CONF))

# 12. Налаштування журналу
state("journal_settings_active", lambda: JournalSettingsDialog(T.id, default_api_factory, journal_info(T, j9m.id)), size=None)


def build_js_archived_conflict():
    d = JournalSettingsDialog(T.id, default_api_factory, journal_info(T, j10.id))
    d.combos["s1_end"].setCurrentIndex(9)  # жовтень: листопадові й грудневі уроки конфліктують
    d._on_save()
    return d


state("journal_settings_archived_conflict", build_js_archived_conflict, size=None)

# 13. Перехід на новий навчальний рік
state("rollover_one_line", lambda: RolloverDialog(plan_for(T_R1)), size=None)
state("rollover_eight_lines", lambda: RolloverDialog(plan_for(T_R8)), size=None)
state("rollover_no_checkbox", lambda: RolloverDialog(plan_for(T_R0)), size=None)
state("rollover_long_names", lambda: RolloverDialog(plan_for(T_RL)), size=None)

# ---------------------------------------------------------------------------
# Контраст і жорстко задані кольори
# ---------------------------------------------------------------------------


def _lin(c: int) -> float:
    x = c / 255
    return x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4


def _lum(hex_color: str) -> float:
    r, g, b = (int(hex_color[i : i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * _lin(r) + 0.7152 * _lin(g) + 0.0722 * _lin(b)


def ratio(a: str, b: str) -> float:
    la, lb = sorted((_lum(a), _lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


PAIRS = [
    ("text", "surface", 4.5), ("text", "bg", 4.5), ("muted", "surface", 4.5), ("muted", "bg", 4.5),
    ("muted", "hover", 4.5), ("muted", "input_bg", 4.5), ("accent_text", "accent", 4.5),
    ("accent_text", "accent_hover", 4.5), ("accent", "accent_soft", 4.5), ("accent", "surface", 4.5),
    ("text", "accent_soft", 4.5), ("danger", "surface", 4.5), ("danger", "danger_soft", 4.5),
    ("mark_absent", "mark_absent_soft", 4.5), ("mark_sick", "mark_sick_soft", 4.5), ("mark_late", "mark_late_soft", 4.5),
    ("text", "lesson_test_soft", 4.5), ("text", "lesson_lab_soft", 4.5), ("text", "lesson_independent_soft", 4.5),
    ("muted", "lesson_test_soft", 4.5), ("muted", "lesson_lab_soft", 4.5), ("muted", "lesson_independent_soft", 4.5),
    ("muted", "border", 4.5), ("mark_absent", "surface", 4.5), ("mark_sick", "surface", 4.5),
    ("mark_late", "surface", 4.5), ("muted", "mark_absent_soft", 4.5), ("accent", "bg", 3.0),
    ("border", "surface", 3.0), ("border", "input_bg", 3.0), ("accent", "input_bg", 3.0),
]
CONTRAST = []
for th in THEMES:
    tokens = theme.TOKENS[th]
    for fg, bg, need in PAIRS:
        r = ratio(tokens[fg], tokens[bg])
        CONTRAST.append({"theme": th, "fg": fg, "bg": bg, "fg_hex": tokens[fg], "bg_hex": tokens[bg],
                         "ratio": round(r, 2), "need": need, "ok": r >= need})

HEX_LINES = []
for path in sorted((ROOT / "src" / "journal" / "ui").glob("*.py")):
    if path.name == "theme.py":
        continue
    for no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if re.search(r"#[0-9a-fA-F]{3,8}\b|QColor\(|\brgb\(", line) and not line.strip().startswith("#"):
            HEX_LINES.append(f"{path.name}:{no}: {line.strip()}")

# ---------------------------------------------------------------------------
# Підсумок
# ---------------------------------------------------------------------------

result = {
    "shots": SHOTS,
    "clipped": CLIPPED,
    "size_notes": SIZE_NOTES,
    "contrast_fail": [c for c in CONTRAST if not c["ok"]],
    "contrast_all": CONTRAST,
    "hardcoded_colors": HEX_LINES,
}
out_path = os.environ.get("QA_OUT")
if out_path:
    Path(out_path).write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")

sess.close()
outer.rollback()  # нічого не залишається в базі
connection.close()
print(f"Готово: {len(SHOTS)} PNG, обрізань: {len(CLIPPED)}, контраст < норми: {len(result['contrast_fail'])}", flush=True)
