"""Concept Map pro Modul: Begriffe aus dem Glossar und wie sie zusammenhängen.

Die Knoten sind die Glossarbegriffe des Moduls (aus allen Vorlesungen). Claude bekommt nur
die kompakten Glossareinträge – nicht die kompletten Notizen – und ergänzt die Beziehungen
(„ist Voraussetzung für“, „ist Spezialfall von“ …) sowie eine Gruppierung nach Themen.
So bleibt die Anfrage klein, auch wenn das Modul viele Vorlesungen hat.
"""

import json
from html import escape

from .glossary import normalize

KINDS = {
    "voraussetzung": "ist Voraussetzung für",
    "spezialfall": "ist Spezialfall von",
    "teil": "ist Teil von",
    "verwendet": "wird verwendet für",
    "verwandt": "hängt zusammen mit",
}

SYSTEM_PROMPT = """\
Du erstellst eine Concept Map für ein Studienmodul: ein Netz aus Begriffen und ihren \
Beziehungen, mit dem Studierende den Zusammenhang des Stoffs verstehen. Du bekommst das \
Glossar des Moduls (Begriffe, Formeln und Sätze mit Definition und der Vorlesung, in der sie \
vorkommen).

knoten: Übernimm die Glossarbegriffe – genau in der Schreibweise des Glossars, keine neuen \
Begriffe. Lass Einträge weg, die mit nichts zusammenhängen. Nimm höchstens {max_terms} \
Begriffe auf; hat das Glossar mehr, wähle die zentralen (Grundbegriffe, wichtige Sätze und \
Verfahren) und lass Randbegriffe und Einzelbeispiele weg. Ordne jedem Begriff eine \
gruppe zu: ein Oberthema aus 1–4 Wörtern (z. B. „Eigenwerte“, „Vektorräume“); insgesamt \
etwa 3 bis 8 Gruppen.

kanten: die wichtigen inhaltlichen Beziehungen zwischen zwei Begriffen, gerichtet von \
„von“ nach „nach“. art ist eine von:
- "voraussetzung": „von“ wird gebraucht, um „nach“ zu verstehen oder zu definieren,
- "spezialfall": „von“ ist ein Spezialfall bzw. eine Art von „nach“,
- "teil": „von“ ist Bestandteil von „nach“,
- "verwendet": „von“ ist ein Werkzeug/Verfahren, mit dem man „nach“ bestimmt oder zeigt,
- "verwandt": sonstiger enger Zusammenhang (z. B. Gegensatz, Äquivalenz).
beschriftung: kurze, konkrete Beschreibung der Beziehung (2–5 Wörter, z. B. „Nullstellen \
liefern die“, „gleich Anzahl der Basisvektoren“), auf Deutsch.

Verbinde jeden Begriff mit mindestens einem anderen, auch über Vorlesungen hinweg – im \
Schnitt höchstens zwei Kanten pro Begriff. Keine doppelten oder trivialen Kanten; lieber die \
tragenden Zusammenhänge als jede denkbare. Stütze \
dich auf die Definitionen im Glossar und auf gesichertes Fachwissen, das zum Stoff gehört."""

SCHEMA = {
    "type": "object",
    "properties": {
        "knoten": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"begriff": {"type": "string"}, "gruppe": {"type": "string"}},
                "required": ["begriff", "gruppe"],
                "additionalProperties": False,
            },
        },
        "kanten": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "von": {"type": "string"},
                    "nach": {"type": "string"},
                    "art": {"type": "string", "enum": list(KINDS)},
                    "beschriftung": {"type": "string"},
                },
                "required": ["von", "nach", "art", "beschriftung"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["knoten", "kanten"],
    "additionalProperties": False,
}


def build_request(*, model: str, effort: str, max_tokens: int, module: str, groups: list[dict],
                  max_terms: int = 80) -> dict:
    """`groups`: zusammengeführte Glossareinträge (glossary.group_entries)."""
    lines = []
    for g in groups:
        lectures = ", ".join(dict.fromkeys(s["lecture_title"] for s in g["sources"]))
        formula = f" Formel: {g['formula']}" if g["formula"] else ""
        lines.append(f"- {g['term']} ({g['kind']}; {lectures}): {g['definition']}{formula}")
    content = (f'<glossar modul="{escape(module)}">\n' + escape("\n".join(lines), quote=False)
               + "\n</glossar>\n\nErstelle jetzt die Concept Map für dieses Modul.")
    return {
        "model": model,
        "max_tokens": max_tokens,
        "thinking": {"type": "adaptive"},
        "output_config": {"effort": effort, "format": {"type": "json_schema", "schema": SCHEMA}},
        "system": SYSTEM_PROMPT.replace("{max_terms}", str(max_terms)),
        "messages": [{"role": "user", "content": content}],
    }


def parse(text: str, known_terms: set[str]) -> tuple[dict, list[str]]:
    """Behält nur Knoten aus dem Glossar und Kanten zwischen ihnen. Rückgabe: (Map, Hinweise).

    `known_terms`: normalisierte Glossarbegriffe des Moduls.
    """
    data = json.loads(text)
    nodes, dropped = {}, []
    for n in data.get("knoten", []):
        norm = normalize(n.get("begriff") or "")
        if norm in known_terms:
            nodes.setdefault(norm, (n.get("gruppe") or "").strip() or "Sonstiges")
        elif norm:
            dropped.append(n.get("begriff").strip())
    edges, seen = [], set()
    for e in data.get("kanten", []):
        a, b = normalize(e.get("von") or ""), normalize(e.get("nach") or "")
        kind = e.get("art") if e.get("art") in KINDS else "verwandt"
        # Begriffe, die nur in einer Kante vorkommen, gehören auch auf die Map.
        for norm in (a, b):
            if norm in known_terms and norm not in nodes:
                nodes[norm] = "Sonstiges"
        if a not in nodes or b not in nodes or a == b or (a, b) in seen:
            continue
        seen.add((a, b))
        edges.append({"from": a, "to": b, "kind": kind, "label": (e.get("beschriftung") or "").strip()})
    warnings = []
    if dropped:
        warnings.append("Nicht im Glossar und daher weggelassen: " + ", ".join(dropped[:20]))
    return {"nodes": [{"norm": k, "group": g} for k, g in nodes.items()], "edges": edges}, warnings


def view(data: dict, groups: list[dict], lectures: list[dict]) -> dict:
    """Daten für die Seite: Knoten mit Definition und Vorlesungen, Kanten, Gruppen, Vorlesungen."""
    by_norm = {g["norm"]: g for g in groups}
    order = {lec["id"]: i for i, lec in enumerate(lectures)}
    nodes = []
    for n in data["nodes"]:
        g = by_norm.get(n["norm"])
        if not g:  # inzwischen nicht mehr im Glossar
            continue
        lecture_ids = sorted({s["lecture_id"] for s in g["sources"] if s["lecture_id"] in order}, key=order.get)
        nodes.append({"id": n["norm"], "term": g["term"], "kind": g["kind"], "group": n["group"],
                      "definition": g["definition"], "formula": g["formula"], "lectures": lecture_ids,
                      "first": order[lecture_ids[0]] if lecture_ids else None})
    ids = {n["id"] for n in nodes}
    edges = [e for e in data["edges"] if e["from"] in ids and e["to"] in ids]
    group_names = list(dict.fromkeys(n["group"] for n in sorted(nodes, key=lambda n: (n["first"] is None, n["first"]))))
    return {"nodes": nodes, "edges": edges, "groups": group_names,
            "lectures": [{"id": lec["id"], "title": lec["title"]} for lec in lectures]}
