"""extra column anchor lesson

Revision ID: a7c41d9e5b02
Revises: fe7a3800028f
Create Date: 2026-11-13 11:30:00.000000

Стовпчики «Тематична»/«Зошит» прив'язуються до конкретного уроку (after_lesson_id), а не лише до
дати: урок, створений пізніше навіть того самого дня, стоїть ПІСЛЯ стовпчика, як у паперовому журналі.
after_date лишається датою-якорем (семестр, межі).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a7c41d9e5b02'
down_revision: Union[str, Sequence[str], None] = 'fe7a3800028f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Остання (за датою, потім id) лекція журналу на дату якоря; якщо уроків на цю дату немає — NULL.
BACKFILL_SQL = (
    "UPDATE extra_columns ec SET after_lesson_id = ("
    "SELECT l.id FROM lessons l WHERE l.journal_id = ec.journal_id AND l.lesson_date = ec.after_date "
    "ORDER BY l.lesson_date DESC, l.id DESC LIMIT 1)"
)
OLD_UNIQUE = "uq_extra_columns_journal_id_kind_after_date"
NEW_UNIQUE = "uq_extra_columns_journal_id_kind_after_lesson_id"
FK_NAME = "fk_extra_columns_after_lesson_id_lessons"
INDEX_NAME = "ix_extra_columns_after_lesson_id"


def upgrade() -> None:
    op.add_column("extra_columns", sa.Column("after_lesson_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        FK_NAME, "extra_columns", "lessons", ["after_lesson_id"], ["id"], ondelete="SET NULL"
    )
    op.create_index(INDEX_NAME, "extra_columns", ["after_lesson_id"])
    op.execute(BACKFILL_SQL)
    op.drop_constraint(OLD_UNIQUE, "extra_columns", type_="unique")
    op.create_index(
        NEW_UNIQUE, "extra_columns", ["journal_id", "kind", "after_lesson_id"],
        unique=True, postgresql_where=sa.text("after_lesson_id IS NOT NULL"),
    )


def downgrade() -> None:
    """Повертає прив'язку лише до дати. Якщо після різних уроків однієї дати стоять стовпчики одного
    виду, лишається найстаріший (за id) — старе обмеження «один на дату» інакше не відновити."""
    op.drop_index(NEW_UNIQUE, table_name="extra_columns")
    op.execute(
        "DELETE FROM extra_columns a USING extra_columns b "
        "WHERE a.journal_id = b.journal_id AND a.kind = b.kind AND a.after_date = b.after_date AND a.id > b.id"
    )
    op.create_unique_constraint(OLD_UNIQUE, "extra_columns", ["journal_id", "kind", "after_date"])
    op.drop_index(INDEX_NAME, table_name="extra_columns")
    op.drop_constraint(FK_NAME, "extra_columns", type_="foreignkey")
    op.drop_column("extra_columns", "after_lesson_id")
