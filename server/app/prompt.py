"""Prompt für die Notizen und Prüfung der Quellenangaben in Claudes Antwort."""

import re
from html import escape

from .transcript import fmt_ts, format_transcript, parse_ts

SYSTEM_PROMPT = """\
Du hilfst Studierenden, Vorlesungen nachzuarbeiten. Du bekommst das Transkript einer \
Vorlesung (automatisch erstellt, kann Hörfehler enthalten) und passende Seiten aus den \
Materialien des Dozenten. Erstelle daraus Lernnotizen auf Deutsch in Markdown.

Aufbau:
1. `# <Titel der Vorlesung>` und ein kurzer Überblick (3–5 Sätze).
2. `## Themen` – gegliedert nach den Themen bzw. Kapiteln der Dozenten-Materialien, in der \
Reihenfolge der Vorlesung. Pro Thema die wichtigsten Aussagen, Definitionen, Herleitungen \
und Beispiele als knappe Stichpunkte. Übernimm Formeln korrekt (LaTeX mit $…$).
3. `## Hinweise des Dozenten` – alles, was der Dozent als prüfungsrelevant, wichtig oder \
häufigen Fehler hervorhebt, und organisatorische Ansagen.
4. `## Nicht im Skript` – Inhalte aus der Vorlesung ohne Entsprechung in den Materialien.
5. `## Offene Punkte` – Stellen, die im Transkript unklar oder widersprüchlich sind.

Quellenangaben (sehr wichtig):
- Belege jeden Stichpunkt mit dem Zeitstempel der Stelle im Video: [hh:mm:ss]. \
Nimm die Zeitstempel aus dem Transkript, erfinde keine.
- Wenn das Thema in den Materialien vorkommt, nenne zusätzlich die Seite: [Kürzel S. Seite], \
z. B. [Skript_VL3 S. 12]. Verwende nur Kürzel und Seiten, die im Material unten stehen.
- Wenn das Transkript vom Skript abweicht, folge bei Fakten dem Skript und markiere die \
Abweichung.

Gib nur die Notizen aus, ohne Vorbemerkung."""

TS_RE = re.compile(r"\[(\d{1,2}:\d{2}:\d{2})\]")
PAGE_RE = re.compile(r"\[([\w\-]+) S\. ?([\w\-]+)\]")


def build_user_content(title: str, segments: list[dict], pages: list[dict]) -> str:
    parts = ["<materialien>"]
    if not pages:
        parts.append("(Für dieses Modul sind noch keine Materialien hochgeladen.)")
    for p in pages:
        parts.append(
            f'<seite kuerzel="{escape(p["kuerzel"])}" seite="{escape(p["label"])}">\n'
            f'{escape(p["text"], quote=False)}\n</seite>'
        )
    parts.append("</materialien>\n")
    parts.append(f"<transkript titel=\"{escape(title)}\">")
    parts.append(escape(format_transcript(segments), quote=False))
    parts.append("</transkript>\n")
    parts.append("Erstelle jetzt die Lernnotizen zu dieser Vorlesung.")
    return "\n".join(parts)


def build_request(
    *, model: str, effort: str, max_tokens: int, title: str, segments: list[dict], pages: list[dict]
) -> dict:
    """Parameter für messages.create – identisch für count_tokens und den Batch-Job."""
    return {
        "model": model,
        "max_tokens": max_tokens,
        "thinking": {"type": "adaptive"},
        "output_config": {"effort": effort},
        "system": SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": build_user_content(title, segments, pages)}],
    }


def validate_citations(notes: str, duration_sec: float, known_pages: set[tuple[str, str]]) -> list[str]:
    """Findet Zeitstempel hinter dem Videoende und Seitenangaben, die es nicht gibt."""
    warnings = []
    for ts in sorted(set(TS_RE.findall(notes))):
        if parse_ts(ts) > duration_sec + 5:
            warnings.append(f"Zeitstempel [{ts}] liegt hinter dem Videoende ({fmt_ts(duration_sec)}).")
    for kuerzel, label in sorted(set(PAGE_RE.findall(notes))):
        if (kuerzel, label) not in known_pages:
            warnings.append(f"Seitenangabe [{kuerzel} S. {label}] passt zu keiner mitgeschickten Seite.")
    return warnings
