"""Klausurvorbereitung pro Modul: eine Datei aus den Notizen aller Vorlesungen.

Eingabe für Claude sind die fertigen Notizen jeder Vorlesung plus die Stellen im
Transkript, an denen der Dozent Klausur, Prüfung, Wichtiges o. Ä. erwähnt – nicht
die kompletten Transkripte, das hält die Kosten klein. Jede Vorlesung bekommt ein
Kürzel (V1, V2, …); Quellen lauten [V3 00:12:34] und werden in der Weboberfläche
zu Links auf die Vorlesung.
"""

import re
from html import escape

from .transcript import fmt_ts, merge_segments, parse_ts

SYSTEM_PROMPT = """\
Du hilfst Studierenden bei der Klausurvorbereitung. Du bekommst die Lernnotizen aller \
bisherigen Vorlesungen eines Moduls sowie Transkript-Stellen, an denen der Dozent Klausur, \
Prüfung oder Wichtiges erwähnt. Erstelle daraus eine Klausurvorbereitung auf Deutsch in Markdown.

Aufbau:
1. `# Klausurvorbereitung – <Modul>` und 2–3 Sätze, worauf es in diesem Modul ankommt.
2. `## Vom Dozenten ausdrücklich genannt` – alles, was der Dozent als klausur- oder \
prüfungsrelevant bezeichnet hat, möglichst wörtlich bzw. sinngemäß, mit Quelle. Nur Belegtes.
3. `## Kernthemen` – die wichtigsten Themen, sortiert nach Klausurrelevanz. Pro Thema: \
eine Einschätzung (**hoch**/**mittel**), was man können muss, zentrale Formeln (LaTeX mit $…$ \
bzw. $$…$$) und Quellen. Begründe die Einschätzung kurz (z. B. „vom Dozenten angekündigt“, \
„in mehreren Vorlesungen wiederholt“, „Grundlage für spätere Themen“).
4. `## Typische Fehler` – vom Dozenten genannte Stolperfallen.
5. `## Übungsfragen` – 8 bis 15 Fragen zur Selbstkontrolle, wie sie in einer Klausur vorkommen \
könnten, jeweils mit Verweis auf die Quelle der Antwort. Keine Lösungen.
6. `## Checkliste` – kurze Liste zum Abhaken (`- [ ] …`).

Quellen (sehr wichtig):
- Zeitstempel immer mit Vorlesungskürzel: [V2 00:41:10]. Nimm nur Zeitstempel, die in den \
Notizen oder Transkript-Stellen der jeweiligen Vorlesung stehen.
- Skriptseiten wie in den Notizen: [Kürzel S. 12].
- Erfinde keine Hinweise des Dozenten. Wenn nichts ausdrücklich als klausurrelevant genannt \
wurde, schreibe das so und stütze die Einschätzung auf Wiederholung und Bedeutung der Themen.

Gib nur die Klausurvorbereitung aus, ohne Vorbemerkung."""

# Wörter, bei denen Dozenten typischerweise auf Prüfungsrelevantes hinweisen.
HINT_RE = re.compile(
    r"klausur|prüfung|pruefung|prüfungsrelevant|examen|wichtig|merken|merkt euch|merken sie sich|"
    r"kommt dran|drankommen|abgefragt|typischer fehler|häufiger fehler|aufpassen|achtung",
    re.IGNORECASE,
)
CITE_RE = re.compile(r"\[V(\d+) (\d{1,2}:\d{2}:\d{2})\]")
MAX_EXCERPTS_PER_LECTURE = 25


def code(index: int) -> str:
    return f"V{index + 1}"


def hint_excerpts(segments: list[dict]) -> list[str]:
    """Transkript-Blöcke (ca. 30 s), in denen ein Hinweiswort fällt – mit Zeitstempel."""
    blocks = merge_segments(segments)
    return [f"[{fmt_ts(b['start'])}] {b['text']}" for b in blocks if HINT_RE.search(b["text"])][
        :MAX_EXCERPTS_PER_LECTURE
    ]


def build_request(*, model: str, effort: str, max_tokens: int, module: str, lectures: list[dict]) -> dict:
    """`lectures`: dicts mit title, notes, segments – in Vorlesungsreihenfolge."""
    parts = [f'<modul name="{escape(module)}">']
    for i, lec in enumerate(lectures):
        parts.append(f'<vorlesung kuerzel="{code(i)}" titel="{escape(lec["title"])}">')
        parts.append("<notizen>\n" + lec["notes"] + "\n</notizen>")
        excerpts = hint_excerpts(lec["segments"])
        if excerpts:
            parts.append("<hinweis_stellen_im_transkript>\n" + escape("\n".join(excerpts), quote=False)
                         + "\n</hinweis_stellen_im_transkript>")
        parts.append("</vorlesung>")
    parts.append("</modul>\n\nErstelle jetzt die Klausurvorbereitung für dieses Modul.")
    return {
        "model": model,
        "max_tokens": max_tokens,
        "thinking": {"type": "adaptive"},
        "output_config": {"effort": effort},
        "system": SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": "\n".join(parts)}],
    }


def legend(lectures: list[dict]) -> str:
    """Zuordnung der Kürzel zu den Vorlesungen, wird vor die Datei gesetzt."""
    lines = ["> **Vorlesungen:** " + " · ".join(f"{code(i)} = {lec['title']}" for i, lec in enumerate(lectures))]
    return "\n".join(lines)


def validate(markdown: str, lectures: list[dict]) -> list[str]:
    """Quellen mit unbekanntem Kürzel oder Zeitstempel hinter dem Videoende."""
    warnings = []
    for num, ts in sorted(set(CITE_RE.findall(markdown))):
        i = int(num) - 1
        if not 0 <= i < len(lectures):
            warnings.append(f"Quelle [V{num} {ts}] verweist auf eine unbekannte Vorlesung.")
        elif parse_ts(ts) > lectures[i]["duration_sec"] + 5:
            warnings.append(f"Zeitstempel [V{num} {ts}] liegt hinter dem Ende von „{lectures[i]['title']}“.")
    return warnings


def link_citations(html: str, lecture_ids: list[int], base: str) -> str:
    """[V3 00:12:34] → Link auf die Vorlesung (im gerenderten HTML)."""
    def repl(m: re.Match) -> str:
        i = int(m.group(1)) - 1
        label = f"[V{m.group(1)} {m.group(2)}]"
        if 0 <= i < len(lecture_ids):
            return f'<a class="ts" href="{base}/lectures/{lecture_ids[i]}">{label}</a>'
        return f'<span class="ts">{label}</span>'
    return CITE_RE.sub(repl, html)
