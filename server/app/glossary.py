"""Glossar pro Modul: Einträge aus den Lernnotizen jeder Vorlesung, zusammengeführt nach Begriff."""

import json
import re
import unicodedata
from html import escape

from .transcript import parse_ts

KINDS = ("Begriff", "Formel", "Satz")

SYSTEM_PROMPT = """\
Du erstellst aus den Lernnotizen einer Vorlesung Einträge für ein Glossar, mit dem Studierende \
für die Klausur lernen. Wähle die wichtigsten Fachbegriffe, Formeln und Sätze (Theoreme, \
Regeln, Gesetze) der Vorlesung aus – in der Regel 10 bis 30 Einträge, keine Allgemeinbegriffe.

Für jeden Eintrag:
- begriff: der Fachbegriff bzw. der übliche Name der Formel/des Satzes, ohne Artikel.
- art: "Begriff", "Formel" oder "Satz".
- definition: 1–3 Sätze auf Deutsch, verständlich ohne die Notizen. Formelzeichen als LaTeX \
in $…$.
- formel: die zentrale Formel als LaTeX ohne $-Zeichen, sonst leerer String.
- zeitstempel: die Zeitstempel (hh:mm:ss), an denen die Notizen den Eintrag belegen.
- seiten: die Seitenangaben aus den Notizen im Format "Kürzel S. Seite".

Übernimm Zeitstempel und Seitenangaben nur aus den Notizen, erfinde keine."""

SCHEMA = {
    "type": "object",
    "properties": {
        "eintraege": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "begriff": {"type": "string"},
                    "art": {"type": "string", "enum": list(KINDS)},
                    "definition": {"type": "string"},
                    "formel": {"type": "string"},
                    "zeitstempel": {"type": "array", "items": {"type": "string"}},
                    "seiten": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["begriff", "art", "definition", "formel", "zeitstempel", "seiten"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["eintraege"],
    "additionalProperties": False,
}

TS_RE = re.compile(r"^\d{1,2}:\d{2}:\d{2}$")
PAGE_RE = re.compile(r"^\[?([\w\-]+) S\. ?([\w\-]+)\]?$")


def build_request(*, model: str, effort: str, max_tokens: int, title: str, notes: str) -> dict:
    return {
        "model": model,
        "max_tokens": max_tokens,
        "thinking": {"type": "adaptive"},
        "output_config": {"effort": effort, "format": {"type": "json_schema", "schema": SCHEMA}},
        "system": SYSTEM_PROMPT,
        "messages": [{
            "role": "user",
            "content": f'<notizen titel="{escape(title)}">\n{notes}\n</notizen>\n\n'
                       "Erstelle die Glossareinträge zu dieser Vorlesung.",
        }],
    }


def normalize(term: str) -> str:
    """Schlüssel zum Zusammenführen: „Satz von Bayes“ == „satz  von bayes“."""
    term = unicodedata.normalize("NFKC", term).casefold()
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s\-]", "", term)).strip()


def sort_key(term: str) -> str:
    """Alphabetisch wie im Deutschen üblich (ä wie a, ß wie ss)."""
    t = term.casefold().replace("ß", "ss")
    return "".join(c for c in unicodedata.normalize("NFD", t) if not unicodedata.combining(c))


def parse_entries(text: str, duration_sec: float, known_pages: set[tuple[str, str]]) -> list[dict]:
    """Liest Claudes JSON und verwirft Quellenangaben, die es nicht gibt."""
    entries = []
    for e in json.loads(text).get("eintraege", []):
        term = (e.get("begriff") or "").strip()
        if not term:
            continue
        timestamps = [t for t in e.get("zeitstempel", [])
                      if TS_RE.match(t) and parse_ts(t) <= duration_sec + 5]
        pages = []
        for p in e.get("seiten", []):
            m = PAGE_RE.match(p.strip())
            if m and (m.group(1), m.group(2)) in known_pages:
                pages.append(f"{m.group(1)} S. {m.group(2)}")
        entries.append({
            "term": term,
            "norm": normalize(term),
            "kind": e.get("art") if e.get("art") in KINDS else "Begriff",
            "definition": (e.get("definition") or "").strip(),
            "formula": (e.get("formel") or "").strip().strip("$").strip(),
            "timestamps": sorted(set(timestamps)),
            "pages": list(dict.fromkeys(pages)),
        })
    return entries


def group_entries(rows: list[dict]) -> list[dict]:
    """Fasst Einträge verschiedener Vorlesungen zum selben Begriff zusammen.

    `rows` enthält je Eintrag zusätzlich `lecture_id` und `lecture_title` und ist nach Vorlesung
    sortiert. Der neueste Eintrag liefert Schreibweise, Art und Hauptdefinition.
    """
    groups: dict[str, dict] = {}
    for r in rows:
        g = groups.setdefault(r["norm"], {"norm": r["norm"], "sources": []})
        g.update(term=r["term"], kind=r["kind"])
        g["sources"].append(r)
    result = []
    for g in groups.values():
        latest = g["sources"][-1]
        g["definition"] = latest["definition"]
        g["formula"] = next((s["formula"] for s in reversed(g["sources"]) if s["formula"]), "")
        # Weitere Definitionen nur zeigen, wenn sie sich unterscheiden.
        g["other_definitions"] = [
            s for s in g["sources"][:-1] if s["definition"] and s["definition"] != latest["definition"]
        ]
        result.append(g)
    return sorted(result, key=lambda g: sort_key(g["term"]))


def initial(term: str) -> str:
    first = sort_key(term)[:1].upper()
    return first if first.isalpha() else "#"


def to_markdown(module_name: str, groups: list[dict], stand: str) -> str:
    lines = [f"# Glossar – {module_name}", "",
             f"_Stand {stand} · {len(groups)} Einträge · automatisch aus den Vorlesungsnotizen erstellt_", ""]
    current = None
    for g in groups:
        letter = initial(g["term"])
        if letter != current:
            lines += [f"## {letter}", ""]
            current = letter
        lines.append(f"**{g['term']}** _({g['kind']})_  ")
        if g["definition"]:
            lines.append(g["definition"])
        if g["formula"]:
            lines += ["", f"$$ {g['formula']} $$"]
        for other in g["other_definitions"]:
            lines += ["", f"> {other['lecture_title']}: {other['definition']}"]
        refs = []
        for s in g["sources"]:
            cites = [f"[{t}]" for t in s["timestamps"]] + [f"[{p}]" for p in s["pages"]]
            refs.append(f"{s['lecture_title']} {' '.join(cites)}".strip())
        lines += ["", "Quellen: " + "; ".join(refs), ""]
    return "\n".join(lines).rstrip() + "\n"
