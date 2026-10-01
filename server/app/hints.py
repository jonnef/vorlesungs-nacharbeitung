"""Prüfungshinweise: nur das, was der Dozent ausdrücklich zur Klausur sagt.

Pro Vorlesung bekommt Claude die Transkript-Stellen rund um Hinweiswörter (mit etwas
Kontext davor und danach) und gibt strukturiert zurück, welche davon echte Aussagen zur
Klausur sind – mit wörtlichem Zitat, Thema, Zeitstempel und passenden Skriptseiten. Jedes
Zitat wird anschließend gegen das Transkript geprüft.
"""

import json
import re
import unicodedata
from html import escape

from .transcript import fmt_ts, merge_segments, parse_ts

KINDS = {
    "klausurrelevant": "Klausurrelevant",
    "nicht_klausurrelevant": "Kommt nicht dran",
    "pruefungsformat": "Klausurformat & Organisation",
    "typischer_fehler": "Typischer Fehler",
}

# Bewusst weit gefasst – Claude entscheidet danach, was wirklich eine Aussage zur Klausur ist.
TRIGGER_RE = re.compile(
    r"klausur|prüfung|pruefung|examen|\btest\b|abgefragt|abfragen|dran ?komm|kommt dran|kommt (auch )?nicht|"
    r"nicht relevant|relevant|wichtig|merken|merkt euch|können müssen|müssen sie können|sollten sie können|"
    r"aufgabe|punkte|hilfsmittel|formelsammlung|taschenrechner|spickzettel|altklausur|probeklausur|"
    r"typische[rn]? fehler|häufige[rn]? fehler|aufpassen|achtung|beliebt|gerne gefragt|lieblingsthema",
    re.IGNORECASE,
)
CONTEXT_BLOCKS = 1          # Blöcke (à ca. 30 s) Kontext vor und nach einer Fundstelle
MAX_BLOCKS_PER_LECTURE = 60

SYSTEM_PROMPT = """\
Du filterst aus Vorlesungstranskripten heraus, was der Dozent AUSDRÜCKLICH über die Klausur \
sagt. Du bekommst Transkript-Stellen (automatisch transkribiert, kann Hörfehler enthalten) und \
die Lernnotizen der Vorlesung.

Nimm nur Aussagen auf, in denen der Dozent selbst klar sagt, dass etwas in der Klausur vorkommt \
oder nicht vorkommt, wie die Klausur abläuft (Aufgabentypen, Hilfsmittel, Punkte, Dauer) oder \
dass etwas ein typischer Fehler ist. Ein bloßes „das ist wichtig“ ohne Bezug zur Klausur oder \
zum Können gehört nur dazu, wenn klar ist, dass es geprüft wird oder beherrscht werden muss \
(„das müssen Sie können“). Keine eigenen Einschätzungen, keine Vermutungen.

Für jeden Hinweis:
- art: "klausurrelevant", "nicht_klausurrelevant", "pruefungsformat" oder "typischer_fehler".
- thema: worauf sich die Aussage bezieht, kurz (z. B. „Austauschverfahren“).
- zitat: die Aussage WÖRTLICH aus dem Transkript, höchstens zwei Sätze; Auslassungen mit „…“.
- zeitstempel: der Zeitstempel (hh:mm:ss) des Transkriptblocks, in dem die Aussage steht.
- seiten: passende Skriptseiten aus den Notizen im Format "Kürzel S. Seite", sonst leer.
- erlaeuterung: ein Satz, was genau gemeint ist und was man dafür können muss.

Gibt es keine solchen Aussagen, liefere eine leere Liste."""

SCHEMA = {
    "type": "object",
    "properties": {
        "hinweise": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "art": {"type": "string", "enum": list(KINDS)},
                    "thema": {"type": "string"},
                    "zitat": {"type": "string"},
                    "zeitstempel": {"type": "string"},
                    "seiten": {"type": "array", "items": {"type": "string"}},
                    "erlaeuterung": {"type": "string"},
                },
                "required": ["art", "thema", "zitat", "zeitstempel", "seiten", "erlaeuterung"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["hinweise"],
    "additionalProperties": False,
}

TS_RE = re.compile(r"^\d{1,2}:\d{2}:\d{2}$")
PAGE_RE = re.compile(r"^\[?([\w\-]+) S\. ?([\w\-]+)\]?$")


def candidate_blocks(segments: list[dict]) -> list[dict]:
    """Transkript-Blöcke mit Hinweiswort plus Kontext davor/danach, in Reihenfolge."""
    blocks = merge_segments(segments)
    keep: set[int] = set()
    for i, b in enumerate(blocks):
        if TRIGGER_RE.search(b["text"]):
            keep.update(range(max(0, i - CONTEXT_BLOCKS), min(len(blocks), i + CONTEXT_BLOCKS + 1)))
    return [blocks[i] for i in sorted(keep)][:MAX_BLOCKS_PER_LECTURE]


def build_request(*, model: str, effort: str, max_tokens: int, title: str, notes: str,
                  blocks: list[dict]) -> dict:
    excerpt = "\n".join(f"[{fmt_ts(b['start'])}] {b['text']}" for b in blocks)
    return {
        "model": model,
        "max_tokens": max_tokens,
        "thinking": {"type": "adaptive"},
        "output_config": {"effort": effort, "format": {"type": "json_schema", "schema": SCHEMA}},
        "system": SYSTEM_PROMPT,
        "messages": [{
            "role": "user",
            "content": f'<vorlesung titel="{escape(title)}">\n'
                       f"<transkript_stellen>\n{escape(excerpt, quote=False)}\n</transkript_stellen>\n"
                       f"<notizen>\n{notes}\n</notizen>\n</vorlesung>\n\n"
                       "Liste alle ausdrücklichen Aussagen des Dozenten zur Klausur auf.",
        }],
    }


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).casefold()
    text = re.sub(r"[„“\"'‚‘’»«]", "", text)
    return re.sub(r"[^\w]+", " ", text).strip()


def quote_found(quote: str, transcript: str) -> bool:
    """Steht das Zitat (Teile zwischen „…“) wörtlich im Transkript? Groß-/Kleinschreibung und
    Satzzeichen spielen keine Rolle."""
    haystack = _norm(transcript)
    parts = [_norm(p) for p in re.split(r"…|\.\.\.", quote)]
    parts = [p for p in parts if len(p) >= 8]
    return bool(parts) and all(p in haystack for p in parts)


def parse(text: str, *, duration_sec: float, transcript: str, known_pages: set[tuple[str, str]]) -> list[dict]:
    entries = []
    for h in json.loads(text).get("hinweise", []):
        kind = h.get("art")
        quote = (h.get("zitat") or "").strip().strip("„“\"")
        ts = (h.get("zeitstempel") or "").strip()
        if kind not in KINDS or not quote or not TS_RE.match(ts) or parse_ts(ts) > duration_sec + 5:
            continue
        pages = []
        for p in h.get("seiten", []):
            m = PAGE_RE.match(p.strip())
            if m and (m.group(1), m.group(2)) in known_pages:
                pages.append(f"{m.group(1)} S. {m.group(2)}")
        entries.append({
            "kind": kind,
            "topic": (h.get("thema") or "").strip() or "Ohne Thema",
            "quote": quote,
            "timestamp": ts,
            "seconds": parse_ts(ts),
            "pages": list(dict.fromkeys(pages)),
            "note": (h.get("erlaeuterung") or "").strip(),
            "verified": quote_found(quote, transcript),
        })
    return entries


def to_markdown(module_name: str, hints: list[dict], stand: str) -> str:
    """Datei für iCloud: nach Art gruppiert, innerhalb chronologisch."""
    lines = [f"# Prüfungshinweise – {module_name}", "",
             f"_Stand {stand} · nur ausdrückliche Aussagen des Dozenten, wörtlich aus den Transkripten_", ""]
    if not hints:
        lines.append("Bisher keine ausdrücklichen Aussagen zur Klausur gefunden.")
    for kind, label in KINDS.items():
        group = [h for h in hints if h["kind"] == kind]
        if not group:
            continue
        lines += [f"## {label}", ""]
        for h in group:
            cites = " ".join([f"[{h['timestamp']}]"] + [f"[{p}]" for p in h["pages"]])
            lines.append(f"- **{h['topic']}** – „{h['quote']}“")
            lines.append(f"  {h['lecture_title']} {cites}" + ("" if h["verified"] else " _(Zitat nicht wörtlich im Transkript gefunden)_"))
            if h["note"]:
                lines.append(f"  {h['note']}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def for_exam_prompt(hints: list[dict]) -> str:
    """Kurzform für die Eingabe der Klausurvorbereitung."""
    return "\n".join(f"[{h['timestamp']}] ({KINDS[h['kind']]}) {h['topic']}: „{h['quote']}“" for h in hints)
