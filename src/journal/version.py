"""Версія застосунку. Джерело істини — pyproject.toml; тест стежить, щоб запасна константа збігалась."""
from importlib import metadata

FALLBACK_VERSION = "0.9.0"  # у зібраній версії метаданих пакета немає


def app_version() -> str:
    try:
        return metadata.version("teacher-journal")
    except metadata.PackageNotFoundError:
        return FALLBACK_VERSION
