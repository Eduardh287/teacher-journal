"""Транзакція + сервіс: єдине місце, де UI відкриває `journal.db.session_scope()` для виклику сервісу."""
from collections.abc import Iterator
from contextlib import contextmanager
from typing import TypeVar

from journal.db import session_scope

Service = TypeVar("Service")


@contextmanager
def service_scope(service_cls: type[Service]) -> Iterator[Service]:
    """`with service_scope(ClassService) as service:` — сервіс у новій транзакції (commit / rollback)."""
    with session_scope() as session:
        yield service_cls(session)
