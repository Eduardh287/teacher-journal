"""semester boundaries

Revision ID: c12d062be128
Revises: 8e3ed2046fb3
Create Date: 2026-11-12 15:44:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c12d062be128'
down_revision: Union[str, Sequence[str], None] = '8e3ed2046fb3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLES = ("teachers", "journals")
# (стовпець, значення за замовчуванням): I семестр вересень-грудень, II січень-червень
COLUMNS = (("s1_start_month", 9), ("s1_end_month", 12), ("s2_start_month", 1), ("s2_end_month", 6))


def upgrade() -> None:
    """Межі семестрів (місяці): глобальні в teachers, знімок для кожного журналу в journals.

    Наявні рядки отримують значення за замовчуванням, тож lessons.semester лишається чинним.
    """
    for table in TABLES:
        for column, default in COLUMNS:
            op.add_column(
                table,
                sa.Column(column, sa.SmallInteger(), nullable=False, server_default=str(default)),
            )
            op.create_check_constraint(
                op.f(f"ck_{table}_{column}"), table, f"{column} BETWEEN 1 AND 12"
            )


def downgrade() -> None:
    for table in TABLES:
        for column, _ in COLUMNS:
            op.drop_constraint(op.f(f"ck_{table}_{column}"), table, type_="check")
            op.drop_column(table, column)
