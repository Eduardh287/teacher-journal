"""Підключення до PostgreSQL: engine, фабрика сесій і помічник для транзакцій.

Engine створюється «ліниво» — при першому зверненні, а не під час імпорту.
Тому застосунок встигає показати зрозуміле вікно помилки, якщо БД не налаштована,
а тести можуть підключитися до окремої тестової бази.
"""
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from journal.config import database_url

_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def init_engine(url: str | None = None) -> Engine:
    """Створює engine для вказаної бази (за замовчуванням — робочої з .env)."""
    global _engine, _session_factory
    if _engine is not None:
        _engine.dispose()
    # hide_parameters: значення (логіни, хеші) не потрапляють у тексти помилок і логи.
    _engine = create_engine(url or database_url(), pool_pre_ping=True, hide_parameters=True)
    _session_factory = sessionmaker(bind=_engine, class_=Session, expire_on_commit=False)
    return _engine


def get_engine() -> Engine:
    if _engine is None:
        init_engine()
    return _engine


@contextmanager
def session_scope() -> Iterator[Session]:
    """Одна дія користувача = одна транзакція: commit при успіху, rollback при помилці."""
    get_engine()
    with _session_factory() as session, session.begin():
        yield session
