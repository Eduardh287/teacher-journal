from sqlalchemy import CheckConstraint, SmallInteger, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from journal.models.base import Base, TimestampMixin


class Teacher(TimestampMixin, Base):
    """Викладач. Усі класи прив'язані до викладача — так можна додати кількох користувачів."""

    __tablename__ = "teachers"
    __table_args__ = tuple(
        CheckConstraint(f"{c} BETWEEN 1 AND 12", name=c)
        for c in ("s1_start_month", "s1_end_month", "s2_start_month", "s2_end_month")
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(50), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[str] = mapped_column(String(150))
    # Глобальні межі семестрів (місяці 1-12); за замовчуванням I: вересень-грудень, II: січень-червень.
    s1_start_month: Mapped[int] = mapped_column(SmallInteger, default=9, server_default="9")
    s1_end_month: Mapped[int] = mapped_column(SmallInteger, default=12, server_default="12")
    s2_start_month: Mapped[int] = mapped_column(SmallInteger, default=1, server_default="1")
    s2_end_month: Mapped[int] = mapped_column(SmallInteger, default=6, server_default="6")

    # Видалення викладача видаляє і його класи (разом з учнями та журналами).
    classes: Mapped[list["SchoolClass"]] = relationship(  # noqa: F821
        back_populates="teacher", cascade="all, delete-orphan"
    )
