"""password throttle and recovery code

Revision ID: b5d2e8f1a3c7
Revises: a7c41d9e5b02
Create Date: 2026-11-14 10:00:00.000000

Етап 7b: лічильник невдалих входів, час блокування та хеш коду відновлення пароля.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b5d2e8f1a3c7'
down_revision: Union[str, Sequence[str], None] = 'a7c41d9e5b02'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "teachers",
        sa.Column("failed_attempts", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column("teachers", sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True))
    op.add_column("teachers", sa.Column("recovery_code_hash", sa.String(length=255), nullable=True))


def downgrade() -> None:
    op.drop_column("teachers", "recovery_code_hash")
    op.drop_column("teachers", "locked_until")
    op.drop_column("teachers", "failed_attempts")
