"""Karten aussortieren: Organisatorisches und vom Dozenten ausdrücklich Ausgeschlossenes.

Pro Modul bekommt Claude alle noch nicht geprüften Karten (Vorderseite + gekürzte Rückseite)
und die Prüfungshinweise des Dozenten. Zurück kommen nur die Karten, die aussortiert werden
sollen, mit Grund. Aussortierte Karten werden archiviert – nicht gelöscht – und lassen sich
unter „Karten verwalten“ wiederherstellen.
"""

import json
from html import escape

REASONS = {
    "organisatorisch": "Organisatorisch",
    "nicht_klausurrelevant": "Laut Dozent nicht klausurrelevant",
    "ohne_lerninhalt": "Ohne Lerninhalt",
}
BACK_CHARS = 300

SYSTEM_PROMPT = """\
Du räumst die Lernkarten (Karteikarten und Übungsaufgaben) eines Studienmoduls auf. \
Sortiere NUR Karten aus, die sicher nicht zum prüfungsrelevanten Stoff gehören:

- "organisatorisch": Organisation statt Fachinhalt – Termine, Fristen, Abgaben, Anmeldung, \
Klausurtermin, Raum, Ablauf der Übungen, Bonuspunkte, Literaturlisten, Sprechstunden, \
Plattformen, Hinweise wie „Übungsblatt 3 ist online“.
- "nicht_klausurrelevant": der Dozent hat das Thema laut <pruefungshinweise_des_dozenten> \
AUSDRÜCKLICH als nicht klausurrelevant bezeichnet („kommt nicht dran“, „müssen Sie nicht \
auswendig können“). Nur bei klarer Übereinstimmung mit dem genannten Thema.
- "ohne_lerninhalt": die Karte prüft kein Fachwissen (z. B. „Worum ging es in der Vorlesung?“, \
„Was ist das Thema von Kapitel 2?“).

Behalte alle Karten mit Fachinhalt – auch wenn der Dozent sie nicht ausdrücklich als \
klausurrelevant markiert hat, und auch Hintergrundwissen, Beispiele und Herleitungen. Im \
Zweifel behalten. Fachliche Fehler auf Karten sind kein Grund zum Aussortieren.

Gib nur die auszusortierenden Karten an: id, grund und eine kurze Begründung (ein Satz)."""

SCHEMA = {
    "type": "object",
    "properties": {
        "aussortieren": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "grund": {"type": "string", "enum": list(REASONS)},
                    "begruendung": {"type": "string"},
                },
                "required": ["id", "grund", "begruendung"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["aussortieren"],
    "additionalProperties": False,
}


def _short(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[:limit - 1] + "…"


def build_request(*, model: str, effort: str, max_tokens: int, module: str, cards: list[dict],
                  hints: str) -> dict:
    """`cards`: Karten wie Service.card() sie liefert; `hints`: Prüfungshinweise als Text."""
    parts = [f'<modul name="{escape(module)}">']
    parts.append("<pruefungshinweise_des_dozenten>\n" + (escape(hints, quote=False) or "(keine)")
                 + "\n</pruefungshinweise_des_dozenten>")
    parts.append("<karten>")
    for c in cards:
        v = c["variants"][0]
        parts.append(f'<karte id="{c["id"]}" art="{c["kind"]}" vorlesung="{escape(c["lecture_title"])}"'
                     f' thema="{escape(c["topic"])}">\nVorderseite: {escape(_short(v["front"], 600), quote=False)}\n'
                     f'Rückseite: {escape(_short(v["back"], BACK_CHARS), quote=False)}\n</karte>')
    parts.append("</karten>\n</modul>\n\nWelche dieser Karten sollen aussortiert werden?")
    return {
        "model": model,
        "max_tokens": max_tokens,
        "thinking": {"type": "adaptive"},
        "output_config": {"effort": effort, "format": {"type": "json_schema", "schema": SCHEMA}},
        "system": SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": "\n".join(parts)}],
    }


def parse(text: str, checked_ids: set[int]) -> dict[int, str]:
    """{card_id: „Grund: Begründung“} – nur Karten, die tatsächlich geprüft wurden."""
    result = {}
    for e in json.loads(text).get("aussortieren", []):
        card_id = e.get("id")
        if card_id in checked_ids:
            label = REASONS.get(e.get("grund"), "Aussortiert")
            note = (e.get("begruendung") or "").strip()
            result[card_id] = f"{label}: {note}" if note else label
    return result
