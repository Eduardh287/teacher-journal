"""Сортування за українським алфавітом.

Робимо це в Python, а не через collation PostgreSQL: на Windows порядок у БД залежить
від локалі системи, а чиста функція дає однаковий результат усюди і легко тестується.
"""
import re

ALPHABET = "абвгґдеєжзиіїйклмнопрстуфхцчшщьюя"
_INDEX = {letter: i for i, letter in enumerate(ALPHABET)}
_APOSTROPHES = "'’ʼ`"
_WORD_BREAKS = " -"  # пробіл і дефіс ідуть перед будь-якою літерою: «Іван П.» < «Іваненко»


def ukrainian_sort_key(text: str) -> tuple:
    """Ключ сортування: регістр і апострофи ігноруються, невідомі символи — після алфавіту."""
    key = []
    for ch in text.casefold():
        if ch in _APOSTROPHES:
            continue
        if ch in _WORD_BREAKS:
            key.append((0, -1))
        elif ch in _INDEX:
            key.append((0, _INDEX[ch]))
        else:
            key.append((1, ord(ch)))
    return tuple(key)


_CLASS_NUMBER = re.compile(r"\s*(\d+)(.*)", re.DOTALL)


def class_name_key(name: str) -> tuple:
    """Природний порядок назв класів: 5-А < 9-А < 10-А (число порівнюється як число)."""
    match = _CLASS_NUMBER.match(name)
    if match:
        return (0, int(match.group(1)), ukrainian_sort_key(match.group(2)))
    return (1, 0, ukrainian_sort_key(name))
