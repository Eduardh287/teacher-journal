"""student row colour

Revision ID: c3f8a1d27e64
Revises: b5d2e8f1a3c7
Create Date: 2026-11-17 10:00:00.000000

Відгук викладачки 1: м'який колір рядка учня (NULL — без кольору).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c3f8a1d27e64'
down_revision: Union[str, Sequence[str], None] = 'b5d2e8f1a3c7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("students", sa.Column("row_color", sa.String(length=20), nullable=True))
    op.create_check_constraint(
        op.f("ck_students_row_color"),
        "students",
        "row_color IS NULL OR row_color IN ('yellow', 'green', 'blue', 'pink', 'purple', 'orange')",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_students_row_color"), "students", type_="check")
    op.drop_column("students", "row_color")
