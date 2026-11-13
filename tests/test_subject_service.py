"""Тести довідника предметів."""
import pytest

from journal.services.subject_service import SubjectError, SubjectService


def test_initial_subjects_present(session):
    names = [s.name for s in SubjectService(session).list_subjects()]
    assert names == ["Алгебра", "Геометрія", "Математика", "ПП ТФВ", "Фізика"]


def test_add_subject_trims_and_sorts(session):
    svc = SubjectService(session)
    added = svc.add_subject("  Астрономія  ")
    assert added.name == "Астрономія"
    assert [s.name for s in svc.list_subjects()][:2] == ["Алгебра", "Астрономія"]


@pytest.mark.parametrize("name", ["", "   ", "х" * 51])
def test_add_subject_invalid(session, name):
    with pytest.raises(SubjectError):
        SubjectService(session).add_subject(name)


def test_add_subject_duplicate_case_insensitive(session):
    with pytest.raises(SubjectError, match="уже є"):
        SubjectService(session).add_subject("алгебра")
