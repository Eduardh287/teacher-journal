"""FakeJournalService має ті самі правила порядку стовпчиків, що й справжній сервіс."""
from datetime import date

from tests.fakes.fake_journal_service import FakeJournalService


def _order(fake, names):
    grid = fake.get_grid(1, 1, 1)
    label = {("lesson", i): n for i, n in names.items()}
    for e in grid.extra_columns:
        label[(e.kind, e.id)] = "Тем" if e.kind == "thematic" else "Зош"
    label[("semester", None)] = "Сем"
    return " | ".join(label[(c.kind, c.id)] for c in grid.columns)


def test_columns_stay_after_their_anchor_lesson():
    fake = FakeJournalService()
    d = date(2026, 11, 13)
    l1, l2 = fake.add_lesson(d), fake.add_lesson(d)
    fake.create_column(1, 1, "thematic", l2)
    fake.create_column(1, 1, "notebook", l2)
    l3, l4 = fake.add_lesson(d), fake.add_lesson(date(2026, 11, 14))
    names = {l1: "У1", l2: "У2", l3: "У3", l4: "У4"}
    assert _order(fake, names) == "У1 | У2 | Тем | Зош | У3 | У4 | Сем"


def test_fake_period_and_reanchor_on_delete():
    fake = FakeJournalService(["Іван"])
    d = date(2026, 11, 13)
    l1, l2 = fake.add_lesson(d), fake.add_lesson(d)
    fake.put_cell(1, l1, grade=6)
    fake.put_cell(1, l2, grade=8)
    t = fake.create_column(1, 1, "thematic", l2)
    l3 = fake.add_lesson(d)
    fake.put_cell(1, l3, grade=12)  # створений пізніше того ж дня → не в періоді тематичної
    assert fake.student_computed(1, 1, 1)[("thematic", t.id)].auto == 7
    fake.move_column(1, t.id, l1)
    assert _order(fake, {l1: "У1", l2: "У2", l3: "У3"}) == "У1 | Тем | У2 | У3 | Сем"


def test_fake_reanchor_previous_in_same_semester_only():
    """Фейк як сервіс: попередній урок того ж семестру — якір; першого уроку ІІ семестру — без якоря."""
    fake = FakeJournalService(school_year="2026-2027")
    l1 = fake.add_lesson(date(2026, 12, 1))   # І семестр
    l2 = fake.add_lesson(date(2026, 12, 8))   # І семестр
    l3 = fake.add_lesson(date(2027, 1, 12))   # ІІ семестр
    t1 = fake.create_column(1, 1, "thematic", l2)
    t2 = fake.create_column(1, 1, "thematic", l3)
    fake.delete_lesson(1, l2)                 # не перший — переходить до l1
    assert next(c for c in fake.columns if c["id"] == t1.id)["after"] == l1
    fake.delete_lesson(1, l3)                 # перший у ІІ семестрі — якоря немає, семестр ІІ
    column = next(c for c in fake.columns if c["id"] == t2.id)
    assert column["after"] is None
    assert fake._semester_of(column["date"]) == 2
