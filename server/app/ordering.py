"""Reihenfolge der Vorlesungen eines Moduls: Datum aus dem Dateinamen, sonst Nummer, sonst Eingang.

Damit „neueste zuerst“ auch stimmt, wenn Videos nachträglich oder durcheinander transkribiert
wurden: Steht in allen Dateinamen ein Datum (14.10.2026, 2026-10-14 …), zählt das; sonst die
Vorlesungsnummer (VL03, Vorlesung 3, 03_…), wenn alle eine haben; sonst der Zeitpunkt, zu dem
die Vorlesung in der App angekommen ist.
"""

import re
from datetime import date

from .lecture_slides import name_keys

FULL_DATE_RES = [
    (re.compile(r"(?<!\d)(\d{4})[-_.](\d{1,2})[-_.](\d{1,2})(?!\d)"), lambda m: (m[1], m[2], m[3])),
    (re.compile(r"(?<!\d)(\d{1,2})\.(\d{1,2})\.(\d{4}|\d{2})(?!\d)"), lambda m: (m[3], m[2], m[1])),
]


def file_date(filename: str) -> date | None:
    """Datum (mit Jahr) aus einem Dateinamen."""
    for rx, parts in FULL_DATE_RES:
        if m := rx.search(filename):
            year, month, day = (int(x) for x in parts(m))
            if year < 100:
                year += 2000
            try:
                return date(year, month, day)
            except ValueError:
                continue
    return None


def _number(lecture: dict) -> int | None:
    numbers = sorted(int(k[1:]) for k in name_keys(lecture["source_filename"]) if k.startswith("n"))
    return numbers[0] if len(numbers) == 1 else None


def annotate(lectures: list[dict]) -> str:
    """Ergänzt je Vorlesung `sort_key` (aufsteigend = älteste zuerst) und `lecture_date`.

    Gibt zurück, wonach sortiert wurde: "date", "number" oder "added".
    """
    dates = [file_date(l["source_filename"]) or file_date(l.get("title") or "") for l in lectures]
    numbers = [_number(l) for l in lectures]
    for lec, d in zip(lectures, dates):
        lec["lecture_date"] = d.isoformat() if d else (lec.get("created_at") or "")[:10]
    if lectures and all(dates):
        basis = "date"
        keys = [(d.isoformat(), l["source_filename"]) for d, l in zip(dates, lectures)]
    elif lectures and all(n is not None for n in numbers):
        basis = "number"
        keys = [(f"{n:04d}", l["source_filename"]) for n, l in zip(numbers, lectures)]
    else:
        basis = "added"
        keys = [(l.get("created_at") or "", l["source_filename"]) for l in lectures]
    order = sorted(range(len(lectures)), key=lambda i: keys[i])
    for rank, i in enumerate(order):
        lectures[i]["sort_key"] = rank
    return basis
