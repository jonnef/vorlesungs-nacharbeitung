"""Bemalte Folien aus der Vorlesung: Zuordnung zur Vorlesung und zur passenden Skriptseite.

Die PDFs werden nur angezeigt (nicht an Claude geschickt). Zur Vorlesung gehören sie über den
Dateinamen (VL03, V3, Vorlesung 3, 03_…, Datum), zur Skriptseite einer Seitenangabe über den
Folientext – Zeichnungen ändern den Text nicht, und so passt es auch, wenn der Dozent nur einen
Teil der Folien oder eine andere Reihenfolge benutzt hat.
"""

import re

_FOLD = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"})
NUMBER_RE = re.compile(
    r"(?:^|[^a-z])(?:vl|v|vorlesung|lecture|lec|termin|sitzung|einheit|session|teil|woche|week)"
    r"[\s_\-.#]*0*(\d{1,2})(?!\d)")
LEADING_RE = re.compile(r"^0*(\d{1,2})(?!\d)(?![.\-]\d)")
DATE_RES = [
    (re.compile(r"(?<!\d)(\d{4})[-_.](\d{1,2})[-_.](\d{1,2})(?!\d)"), lambda m: (m[2], m[3])),   # 2026-10-14
    (re.compile(r"(?<!\d)(\d{1,2})\.(\d{1,2})\.(?:\d{2,4})?(?!\d)"), lambda m: (m[2], m[1])),    # 14.10.(2026)
    (re.compile(r"(?<!\d)(\d{2})(\d{2})(\d{2})(?!\d)"), lambda m: (m[2], m[3])),                # 261014
]
MIN_WORDS = 3         # kürzere Folientexte (nur ein Titel) lassen sich nicht sicher zuordnen
MIN_SCORE = 0.6       # Anteil der Wörter der Skriptseite, die auf der bemalten Seite stehen müssen
SHORT_TEXT = 6        # bei so wenigen Wörtern müssen alle passen


def _fold(text: str) -> str:
    return text.casefold().translate(_FOLD)


def name_keys(filename: str) -> set[str]:
    """Merkmale eines Dateinamens, an denen Video und Folien zusammenpassen: Nummer und Datum."""
    stem = _fold(re.sub(r"\.[a-z0-9]{2,4}$", "", filename.strip(), flags=re.I))
    keys = {f"n{int(m)}" for m in NUMBER_RE.findall(stem)}
    if not keys and (m := LEADING_RE.match(stem)):
        keys.add(f"n{int(m.group(1))}")
    for rx, parts in DATE_RES:
        for m in rx.finditer(stem):
            month, day = parts(m)
            if 1 <= int(month) <= 12 and 1 <= int(day) <= 31:
                keys.add(f"d{int(month):02d}-{int(day):02d}")
    return keys


def match_lecture(filename: str, lectures: list[dict]) -> int | None:
    """ID der einzigen Vorlesung (dicts mit id, source_filename, title), die zum Dateinamen passt."""
    keys = name_keys(filename)
    if not keys:
        return None
    hits = [l["id"] for l in lectures
            if keys & (name_keys(l["source_filename"]) | name_keys(l.get("title") or ""))]
    return hits[0] if len(set(hits)) == 1 else None


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"\w{3,}", _fold(text)) if not w.isdigit()}


def best_page(script_text: str, pages: list[dict], script_page_count: int | None = None,
              script_index: int | None = None) -> dict | None:
    """Die bemalte Seite (dict mit slide_id, page_index, text, page_count) zur Skriptseite.

    Bevorzugt über den Text; haben die bemalten Folien gar keinen Text (eingescannt) und genauso
    viele Seiten wie das Skript, über die Seitennummer.
    """
    wanted = _words(script_text)
    if len(wanted) >= MIN_WORDS:
        best, best_score = None, 0.0
        for page in pages:
            score = len(wanted & _words(page["text"])) / len(wanted)
            if score > best_score:
                best, best_score = page, score
        needed = 1.0 if len(wanted) < SHORT_TEXT else MIN_SCORE
        if best is not None and best_score >= needed:
            return best
    if script_index is not None and script_page_count:
        textless = [p for p in pages if not _words(p["text"]) and p["page_count"] == script_page_count]
        for page in textless:
            if page["page_index"] == script_index:
                return page
    return None
