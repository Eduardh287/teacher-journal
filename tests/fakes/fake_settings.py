"""Фейки сервісів налаштувань для тестів інтерфейсу."""
from contextlib import contextmanager

from journal.services.semesters import DEFAULT_BOUNDARIES


class FakeSettingsService:
    def __init__(self, boundaries=DEFAULT_BOUNDARIES, updated: int = 2, error: Exception | None = None) -> None:
        self.boundaries = boundaries
        self.updated = updated
        self.error = error
        self.saved: list = []

    def get_semesters(self, teacher_id):
        return self.boundaries

    def set_semesters(self, teacher_id, boundaries):
        if self.error is not None:
            raise self.error
        self.saved.append(boundaries)
        self.boundaries = boundaries
        return self.updated

    def factory(self):
        @contextmanager
        def make():
            yield self

        return make


class FakeSubjectService:
    def __init__(self, names=("Алгебра", "Фізика")) -> None:
        from journal.services.subject_service import SubjectInfo

        self._info = SubjectInfo
        self.names = list(names)

    def list_subjects(self):
        return [self._info(i, n) for i, n in enumerate(self.names, 1)]

    def add_subject(self, name):
        from journal.services.subject_service import SubjectError

        name = name.strip()
        if name in self.names:
            raise SubjectError(f"Предмет «{name}» уже є")
        self.names.append(name)

    def factory(self):
        @contextmanager
        def make():
            yield self

        return make
