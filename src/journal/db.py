"""Підключення до PostgreSQL: engine, фабрика сесій і помічник для транзакцій."""
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from journal.config import database_url

engine = create_engine(database_url(), echo=False, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)


@contextmanager
def session_scope() -> Iterator[Session]:
    """Одна дія користувача = одна транзакція: commit при успіху, rollback при помилці."""
    with SessionLocal() as session, session.begin():
        yield session
