"""Prompt für die Notizen und Prüfung der Quellenangaben in Claudes Antwort."""

import re
from html import escape

from .transcript import fmt_ts, format_transcript, parse_ts

SYSTEM_PROMPT = """\
Du hilfst Studierenden, Vorlesungen nachzuarbeiten. Du bekommst das Transkript einer \
Vorlesung (automatisch erstellt, kann Hörfehler enthalten) und passende Seiten aus den \
Materialien des Dozenten. Erstelle daraus Lernnotizen auf Deutsch in Markdown, die man \
in einer Web-App liest: Abschnitte lassen sich dort einklappen, Kästen (Callouts) sind \
aufklappbar, Mermaid-Diagramme werden gezeichnet, Formeln mit KaTeX gesetzt.

Aufbau:
1. `# <Titel der Vorlesung>` und ein kurzer Überblick (3–5 Sätze).
2. `## Themen` – pro Thema bzw. Kapitel der Dozenten-Materialien ein Unterabschnitt \
`### <Thema>`, in der Reihenfolge der Vorlesung. Darin:
   - die Kernaussagen, Definitionen und Formeln als knappe Stichpunkte (Formeln in LaTeX mit $…$ \
bzw. $$…$$),
   - zu jedem Thema, bei dem es dem Verständnis hilft, ein **Beispiel** als zugeklappter Kasten \
(siehe unten): konkret und vollständig durchgerechnet bzw. ausgeführt. Nimm bevorzugt die \
Beispiele des Dozenten (mit Zeitstempel). Fehlt eines, denk dir ein passendes aus und schreibe \
„(eigenes Beispiel)“ in den Titel.
   - längere Herleitungen (mehr als drei Schritte) als zugeklappter Kasten `[!proof]-`,
   - ein **Diagramm**, wenn ein Ablauf, ein Zusammenhang, eine Hierarchie/Einteilung, Zustände, \
eine Zeitachse oder ein Funktionsverlauf so leichter zu verstehen ist – nicht bei jedem Thema, \
nur wo es wirklich hilft.
   - Zeigt eine Folie des Dozenten eine wichtige Grafik, verweise auf die Seite \
([Kürzel S. Seite]); die App blendet die Folie dann ein. Zeichne sie nicht nach.
3. `## Hinweise des Dozenten` – alles, was der Dozent als prüfungsrelevant, wichtig oder \
häufigen Fehler hervorhebt, und organisatorische Ansagen.
4. `## Nicht im Skript` – Inhalte aus der Vorlesung ohne Entsprechung in den Materialien.
5. `## Offene Punkte` – Stellen, die im Transkript unklar oder widersprüchlich sind.

Kästen (Callouts), genau in dieser Form, jede Zeile beginnt mit „> “, Leerzeilen im Kasten als „>“:
> [!example]- Beispiel: <kurzer Titel>
> Inhalt …
Typen: `example` (Beispiel), `proof` (Herleitung), `diagram` (Diagramm). „-“ hinter dem Typ = \
zugeklappt (Beispiele, Herleitungen), „+“ = aufgeklappt (Diagramme). Kästen stehen für sich, \
nicht innerhalb von Aufzählungen; davor und danach eine Leerzeile.

Diagramme: im Kasten `> [!diagram]+ <Titel>` ein Codeblock ```mermaid (jede Zeile ebenfalls mit „> “).
- Nur gültige Mermaid-Syntax: flowchart TD/LR, sequenceDiagram, stateDiagram-v2, classDiagram, \
mindmap, timeline oder für Funktionsverläufe xychart-beta (Stützstellen selbst ausrechnen).
- Höchstens etwa 15 Knoten, Beschriftungen kurz und in Anführungszeichen (A["Text"]), \
kein LaTeX und keine Sonderzeichen wie ( ) [ ] { } in unquotierten Beschriftungen.

Quellenangaben (sehr wichtig):
- Belege jeden Stichpunkt mit dem Zeitstempel der Stelle im Video: [hh:mm:ss]. \
Nimm die Zeitstempel aus dem Transkript, erfinde keine. Eigene Beispiele bekommen keinen Zeitstempel.
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
