"""restrict grade deletes

Етап 5: видалення класу, журналу чи учня більше не знищує оцінки каскадом —
БД відмовляє (RESTRICT). Каскад лишається лише для lesson_entries.lesson_id
(видалення уроку свідомо прибирає його клітинки).

Revision ID: 2fadab9e218d
Revises: 4399f0e8a6d1
Create Date: 2026-11-12 07:59:00

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '2fadab9e218d'
down_revision: Union[str, Sequence[str], None] = '4399f0e8a6d1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# (таблиця, колонка, батьківська таблиця) — імена FK за naming convention
_FKS = [
    ("journals", "class_id", "classes"),
    ("lessons", "journal_id", "journals"),
    ("final_grades", "journal_id", "journals"),
    ("lesson_entries", "student_id", "students"),
    ("final_grades", "student_id", "students"),
]


def _recreate_fks(ondelete: str) -> None:
    for table, column, parent in _FKS:
        name = f"fk_{table}_{column}_{parent}"
        op.drop_constraint(name, table, type_="foreignkey")
        op.create_foreign_key(name, table, parent, [column], ["id"], ondelete=ondelete)


def upgrade() -> None:
    """Upgrade schema."""
    _recreate_fks("RESTRICT")
    op.drop_index("ix_lessons_journal_id", table_name="lessons")
    op.create_index(
        "ix_lessons_journal_semester_date", "lessons", ["journal_id", "semester", "lesson_date"]
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_lessons_journal_semester_date", table_name="lessons")
    op.create_index("ix_lessons_journal_id", "lessons", ["journal_id"])
    _recreate_fks("CASCADE")
