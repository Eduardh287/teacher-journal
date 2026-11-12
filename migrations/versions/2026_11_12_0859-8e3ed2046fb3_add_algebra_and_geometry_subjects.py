"""add algebra and geometry subjects

Revision ID: 8e3ed2046fb3
Revises: 2fadab9e218d
Create Date: 2026-11-12 08:59:57.103293

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8e3ed2046fb3'
down_revision: Union[str, Sequence[str], None] = '2fadab9e218d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


NEW_SUBJECTS = ("Алгебра", "Геометрія")


def upgrade() -> None:
    """Викладачка веде алгебру й геометрію окремо (відгук після показу). «Математика» лишається."""
    for name in NEW_SUBJECTS:
        op.execute(
            sa.text("INSERT INTO subjects (name) VALUES (:name) ON CONFLICT (name) DO NOTHING")
            .bindparams(name=name)
        )


def downgrade() -> None:
    """Прибирає ці предмети, лише якщо для них ще немає журналів (дані не губимо)."""
    for name in NEW_SUBJECTS:
        op.execute(
            sa.text(
                "DELETE FROM subjects s WHERE s.name = :name "
                "AND NOT EXISTS (SELECT 1 FROM journals j WHERE j.subject_id = s.id)"
            ).bindparams(name=name)
        )
