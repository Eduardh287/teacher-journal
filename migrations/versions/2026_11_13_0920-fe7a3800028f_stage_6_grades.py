"""stage 6 grades

Revision ID: fe7a3800028f
Revises: c12d062be128
Create Date: 2026-11-13 09:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'fe7a3800028f'
down_revision: Union[str, Sequence[str], None] = 'c12d062be128'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

OLD_TYPES = ('regular', 'test', 'lab', 'independent')
NEW_TYPES = OLD_TYPES + ('quiz', 'project')
GRADE_OR_NA = "(grade IS NOT NULL AND NOT is_na) OR (grade IS NULL AND is_na)"
NEW_SUBJECT = "ПП ТФВ"


def _lesson_type_check(types: tuple[str, ...]) -> None:
    op.drop_constraint(op.f("ck_lessons_lesson_type"), "lessons", type_="check")
    values = ", ".join(f"'{t}'" for t in types)
    op.create_check_constraint(op.f("ck_lessons_lesson_type"), "lessons", f"lesson_type IN ({values})")


def upgrade() -> None:
    """Етап 6: д/з, типи «Тест»/«Проєкт», стовпчики без дати, ручне «н/а», предмет «ПП ТФВ»."""
    op.add_column("lessons", sa.Column("homework", sa.Text(), nullable=True))
    _lesson_type_check(NEW_TYPES)

    op.create_table(
        "extra_columns",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("journal_id", sa.Integer(), nullable=False),
        sa.Column(
            "kind",
            sa.Enum("thematic", "notebook", name="extra_column_kind", native_enum=False,
                    create_constraint=True, length=20),
            nullable=False,
        ),
        sa.Column("semester", sa.SmallInteger(), nullable=False),
        sa.Column("after_date", sa.Date(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("semester IN (1, 2)", name=op.f("ck_extra_columns_semester")),
        sa.ForeignKeyConstraint(["journal_id"], ["journals.id"],
                                name=op.f("fk_extra_columns_journal_id_journals"), ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_extra_columns")),
        sa.UniqueConstraint("journal_id", "kind", "after_date",
                            name=op.f("uq_extra_columns_journal_id_kind_after_date")),
    )
    op.create_table(
        "extra_grades",
        sa.Column("column_id", sa.Integer(), nullable=False),
        sa.Column("student_id", sa.Integer(), nullable=False),
        sa.Column("grade", sa.SmallInteger(), nullable=True),
        sa.Column("is_na", sa.Boolean(), server_default="false", nullable=False),
        sa.CheckConstraint("grade BETWEEN 1 AND 12", name=op.f("ck_extra_grades_grade_range")),
        sa.CheckConstraint(GRADE_OR_NA, name=op.f("ck_extra_grades_grade_or_na")),
        sa.ForeignKeyConstraint(["column_id"], ["extra_columns.id"],
                                name=op.f("fk_extra_grades_column_id_extra_columns"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["student_id"], ["students.id"],
                                name=op.f("fk_extra_grades_student_id_students"), ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("column_id", "student_id", name=op.f("pk_extra_grades")),
    )
    op.create_index(op.f("ix_extra_grades_student_id"), "extra_grades", ["student_id"])

    op.add_column("final_grades", sa.Column("is_na", sa.Boolean(), server_default="false", nullable=False))
    op.alter_column("final_grades", "grade", existing_type=sa.SmallInteger(), nullable=True)
    op.create_check_constraint(op.f("ck_final_grades_grade_or_na"), "final_grades", GRADE_OR_NA)

    op.execute(
        sa.text("INSERT INTO subjects (name) VALUES (:name) ON CONFLICT (name) DO NOTHING")
        .bindparams(name=NEW_SUBJECT)
    )


def downgrade() -> None:
    """Повертає схему етапу 5. Ручні «н/а» й стовпчики без дати втрачаються; нові типи уроків → regular."""
    op.execute(
        sa.text(
            "DELETE FROM subjects s WHERE s.name = :name "
            "AND NOT EXISTS (SELECT 1 FROM journals j WHERE j.subject_id = s.id)"
        ).bindparams(name=NEW_SUBJECT)
    )

    op.drop_constraint(op.f("ck_final_grades_grade_or_na"), "final_grades", type_="check")
    op.execute("DELETE FROM final_grades WHERE grade IS NULL")
    op.alter_column("final_grades", "grade", existing_type=sa.SmallInteger(), nullable=False)
    op.drop_column("final_grades", "is_na")

    op.drop_index(op.f("ix_extra_grades_student_id"), table_name="extra_grades")
    op.drop_table("extra_grades")
    op.drop_table("extra_columns")

    op.execute("UPDATE lessons SET lesson_type = 'regular' WHERE lesson_type IN ('quiz', 'project')")
    _lesson_type_check(OLD_TYPES)
    op.drop_column("lessons", "homework")
