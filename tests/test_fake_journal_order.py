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
