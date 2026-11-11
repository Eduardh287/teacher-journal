from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from journal.models.base import Base, TimestampMixin


class Teacher(TimestampMixin, Base):
    """Викладач. Усі класи прив'язані до викладача — так можна додати кількох користувачів."""

    __tablename__ = "teachers"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(50), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[str] = mapped_column(String(150))

    classes: Mapped[list["SchoolClass"]] = relationship(back_populates="teacher")  # noqa: F821
