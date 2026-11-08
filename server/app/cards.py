"""Lernen: Karteikarten und Übungsaufgaben aus den Notizen, alle Module in einem Pool.

Pro Vorlesung erstellt Claude Karteikarten (Frage → Antwort) und – bei rechenlastigem
Stoff – Übungsaufgaben mit vollständigem Lösungsweg. Jede Aufgabe kommt in mehreren
Varianten mit anderen Zahlen; bei jeder Wiederholung erscheint die nächste Variante, damit
man den Rechenweg übt und nicht das Ergebnis auswendig lernt. Aufgaben, für die man einen
Taschenrechner braucht, sind markiert und lassen sich beim Lernen ausblenden.

Wiederholt wird nach einem vereinfachten SM-2-Verfahren (wie Anki): vier Bewertungen,
der Abstand wächst mit jeder richtigen Antwort.
"""

import json
import re
from datetime import date, timedelta
from html import escape

from .glossary import normalize
from .selection import approx_tokens
from .transcript import parse_ts

KINDS = ("karte", "aufgabe")

SYSTEM_PROMPT = """\
Du erstellst aus den Lernnotizen einer Vorlesung Lernmaterial für eine App mit Wiederholung \
in wachsenden Abständen (wie Anki). Es gibt zwei Arten:

1. art "karte" – Karteikarte mit einer Frage und einer kurzen Antwort (1–4 Sätze oder eine \
Formel). Eine Karte prüft genau eine Sache: Definition, Aussage eines Satzes mit \
Voraussetzungen, Gegenbeispiel, Kernidee eines Beweises, Schritte eines Verfahrens, \
Zusammenhang zweier Begriffe. Frage so, dass man aktiv erinnern muss – keine Ja/Nein-Fragen, \
keine Antwort in der Frage.

2. art "aufgabe" – Übungsaufgabe, die du selbst stellst UND vollständig löst, im Stil von \
Übungsblättern und Klausuren (z. B. „Berechnen Sie …“, „Zeigen Sie …“, „Bestimmen Sie …“). \
Erstelle pro Aufgabe genau 3 Varianten desselben Aufgabentyps mit anderen Zahlen bzw. \
Funktionen/Matrizen, damit man beim Wiederholen den Weg übt und nicht das Ergebnis \
auswendig lernt. Für jede Variante:
   - vorderseite: der Aufgabentext mit konkreten Zahlen (keine Platzhalter),
   - rueckseite: der vollständige Lösungsweg Schritt für Schritt, jeder Schritt nachvollziehbar,
   - ergebnis: das Endergebnis in einer Zeile.
   Rechne jede Lösung sorgfältig nach. Wähle Zahlen so, dass die Rechnung aufgeht (glatte \
Eigenwerte, kürzbare Brüche usw.), sofern die Aufgabe nicht gerade das Runden übt.
   taschenrechner: true nur, wenn man die Aufgabe ohne Taschenrechner nicht sinnvoll lösen \
kann (z. B. krumme Dezimalzahlen, Logarithmen, Wurzeln ohne glattes Ergebnis). Bevorzuge \
Aufgaben, die mit Stift und Papier gehen.

Mischung: Richte dich nach dem Stoff. Bei Rechenstoff (Mathematik, Statistik, Physik, \
Technik, Rechnungswesen …) etwa 4 bis 8 Aufgaben und 8 bis 15 Karten; bei Stoff ohne \
Rechnungen nur Karten (etwa 10 bis 25) und keine Aufgaben. Wähle das Wichtigste, nicht jedes \
Detail. Bei Karten hat „varianten“ genau einen Eintrag, „ergebnis“ ist dort ein leerer String.

Für jeden Eintrag außerdem:
- thema: kurzes Thema (2–5 Wörter), z. B. „Eigenwerte“.
- zeitstempel: Zeitstempel (hh:mm:ss) aus den Notizen, die den Inhalt belegen.
- seiten: Seitenangaben aus den Notizen im Format "Kürzel S. Seite".

Schreibe auf Deutsch. Formeln als LaTeX in $…$ bzw. $$…$$ (Matrizen z. B. mit \
\\begin{pmatrix}…\\end{pmatrix}); Markdown (Aufzählungen, Absätze) ist erlaubt. Übernimm \
Zeitstempel und Seitenangaben nur aus den Notizen, erfinde keine. Inhaltlich darfst du über \
die Notizen hinausgehen, wenn es zum Üben nötig ist (neue Zahlen, neue Beispiele), aber \
nicht über den Stoff der Vorlesung hinaus."""

SCHEMA = {
    "type": "object",
    "properties": {
        "eintraege": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "art": {"type": "string", "enum": list(KINDS)},
                    "thema": {"type": "string"},
                    "taschenrechner": {"type": "boolean"},
                    "varianten": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "vorderseite": {"type": "string"},
                                "rueckseite": {"type": "string"},
                                "ergebnis": {"type": "string"},
                            },
                            "required": ["vorderseite", "rueckseite", "ergebnis"],
                            "additionalProperties": False,
                        },
                    },
                    "zeitstempel": {"type": "array", "items": {"type": "string"}},
                    "seiten": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["art", "thema", "taschenrechner", "varianten", "zeitstempel", "seiten"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["eintraege"],
    "additionalProperties": False,
}

TS_RE = re.compile(r"^\d{1,2}:\d{2}:\d{2}$")
PAGE_RE = re.compile(r"^\[?([\w\-]+) S\. ?([\w\-]+)\]?$")
CITED_PAGE_RE = re.compile(r"\[([\w\-]+) S\. ?([\w\-]+)\]")


def cited_pages(notes: str, pages: list[dict], max_tokens: int) -> list[dict]:
    """Die in den Notizen zitierten Skriptseiten (in Reihenfolge des ersten Zitats), bis zum Token-Deckel.

    Für Aufgaben ist das Skript oft die bessere Quelle als das Transkript – an der Tafel
    Geschriebenes fehlt dort.
    """
    by_key = {(p["kuerzel"], p["label"]): p for p in pages}
    chosen, used = [], 0
    for key in dict.fromkeys(CITED_PAGE_RE.findall(notes)):
        page = by_key.get(key)
        if not page or not page["text"].strip():
            continue
        cost = approx_tokens(page["text"])
        if used + cost > max_tokens:
            break
        chosen.append(page)
        used += cost
    return chosen


def build_request(*, model: str, effort: str, max_tokens: int, title: str, notes: str,
                  pages: list[dict]) -> dict:
    parts = [f'<notizen titel="{escape(title)}">\n{notes}\n</notizen>']
    if pages:
        parts.append("<skriptseiten>")
        for p in pages:
            parts.append(f'<seite kuerzel="{escape(p["kuerzel"])}" seite="{escape(p["label"])}">\n'
                         f'{escape(p["text"], quote=False)}\n</seite>')
        parts.append("</skriptseiten>")
    parts.append("Erstelle jetzt die Karteikarten und Übungsaufgaben zu dieser Vorlesung.")
    return {
        "model": model,
        "max_tokens": max_tokens,
        "thinking": {"type": "adaptive"},
        "output_config": {"effort": effort, "format": {"type": "json_schema", "schema": SCHEMA}},
        "system": SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": "\n\n".join(parts)}],
    }


def parse(text: str, duration_sec: float, known_pages: set[tuple[str, str]]) -> list[dict]:
    """Liest Claudes JSON, verwirft leere Einträge und Quellenangaben, die es nicht gibt."""
    items = []
    for e in json.loads(text).get("eintraege", []):
        kind = e.get("art") if e.get("art") in KINDS else "karte"
        variants = []
        for v in e.get("varianten") or []:
            front = (v.get("vorderseite") or "").strip()
            back = (v.get("rueckseite") or "").strip()
            if front and back:
                variants.append({"front": front, "back": back, "result": (v.get("ergebnis") or "").strip()})
        if not variants:
            continue
        if kind == "karte":
            variants = variants[:1]
        timestamps = [t for t in e.get("zeitstempel", [])
                      if TS_RE.match(t) and parse_ts(t) <= duration_sec + 5]
        pages = []
        for p in e.get("seiten", []):
            m = PAGE_RE.match(p.strip())
            if m and (m.group(1), m.group(2)) in known_pages:
                pages.append(f"{m.group(1)} S. {m.group(2)}")
        items.append({
            "kind": kind,
            "topic": (e.get("thema") or "").strip(),
            "calculator": bool(e.get("taschenrechner")) and kind == "aufgabe",
            "variants": variants,
            "norm": normalize(variants[0]["front"]),
            "timestamps": sorted(set(timestamps)),
            "pages": list(dict.fromkeys(pages)),
        })
    return items


# ---------- Wiederholung (vereinfachtes SM-2) ----------

GRADES = {1: "Nochmal", 2: "Schwer", 3: "Gut", 4: "Leicht"}
START_EASE = 2.5
MIN_EASE = 1.3
MAX_INTERVAL = 365


def schedule(state: dict, grade: int, today: date) -> dict:
    """Neuer Lernstand nach einer Bewertung.

    `state`: reps (richtige Antworten in Folge), interval_days, ease, lapses.
    „Nochmal“ setzt die Karte zurück; sie kommt noch heute wieder dran.
    """
    if grade not in GRADES:
        raise ValueError("Bewertung muss 1–4 sein.")
    reps, interval, ease, lapses = state["reps"], state["interval_days"], state["ease"], state["lapses"]
    if grade == 1:
        return {"reps": 0, "interval_days": 0, "ease": max(MIN_EASE, ease - 0.2),
                "lapses": lapses + (1 if reps else 0), "due": today.isoformat()}
    if grade == 2:
        interval = 1 if reps == 0 else max(interval + 1, round(interval * 1.2))
        ease = max(MIN_EASE, ease - 0.15)
    elif grade == 3:
        interval = 1 if reps == 0 else 3 if reps == 1 else max(interval + 1, round(interval * ease))
    else:
        interval = 4 if reps == 0 else max(interval + 2, round(interval * ease * 1.3))
        ease = ease + 0.15
    interval = min(interval, MAX_INTERVAL)
    return {"reps": reps + 1, "interval_days": interval, "ease": round(ease, 2), "lapses": lapses,
            "due": (today + timedelta(days=interval)).isoformat()}


def interval_label(days: int) -> str:
    if days <= 0:
        return "heute"
    if days < 30:
        return f"{days} T."
    if days < 365:
        return f"{round(days / 30)} Mon."
    return "1 J."


def variant_for(card: dict) -> tuple[int, dict]:
    """Bei jeder Wiederholung die nächste Variante (Aufgaben mit anderen Zahlen)."""
    variants = card["variants"]
    i = card["views"] % len(variants)
    return i, variants[i]


def card_markdown(card: dict, variant: dict) -> tuple[str, str]:
    """Vorder- und Rückseite als Markdown; die Rückseite endet mit Ergebnis und Quellen."""
    back = variant["back"]
    if variant.get("result"):
        back += f"\n\n**Ergebnis:** {variant['result']}"
    cites = [f"[{t}]" for t in card["timestamps"]] + [f"[{p}]" for p in card["pages"]]
    if cites:
        back += "\n\nQuelle: " + " ".join(cites)
    return variant["front"], back
