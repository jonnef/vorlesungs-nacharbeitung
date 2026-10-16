"""Suche in allen Notizen (und auf Wunsch Transkripten) eines Moduls.

Groß-/Kleinschreibung egal, Umlaute dürfen auch als ae/oe/ue/ss getippt werden. Mehrere
Wörter müssen alle im selben Abschnitt (bzw. Transkript-Block) vorkommen; in "…" gesetzte
Wörter werden als zusammenhängende Phrase gesucht.
"""

import re
from html import escape

from .transcript import fmt_ts, merge_segments

MAX_LINES_PER_SECTION = 3
MAX_TRANSCRIPT_HITS = 8
SNIPPET_CHARS = 220

_FOLD = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"})


def fold(text: str) -> str:
    return text.casefold().translate(_FOLD)


def terms(query: str) -> list[str]:
    """Suchbegriffe: Phrasen in Anführungszeichen bleiben zusammen."""
    found = [p for p in re.findall(r'"([^"]+)"|(\S+)', query)]
    return [fold((a or b).strip()) for a, b in found if (a or b).strip()][:8]


def _plain(line: str) -> str:
    """Markdown-Zeile ohne Auszeichnung, wie sie im Ergebnis gezeigt wird."""
    line = re.sub(r"^\s*(?:>\s*)+", "", line)            # Callout-/Zitat-Präfix
    line = re.sub(r"^\[!\w+\][+-]?\s*", "", line)        # Callout-Typ
    line = re.sub(r"^\s*(?:[-*+]|\d+[.)])\s+(\[[ x]\]\s+)?", "", line)
    line = re.sub(r"^#+\s*", "", line)
    return line.replace("**", "").replace("`", "").strip()


def _positions(text: str, needle: str) -> list[int]:
    """Treffer von needle (gefaltet) im Originaltext – Zuordnung über den gefalteten Text."""
    folded, mapping = [], []
    for i, ch in enumerate(text):
        f = fold(ch)
        folded.append(f)
        mapping.extend([i] * len(f))
    hay = "".join(folded)
    out, start = [], 0
    while (k := hay.find(needle, start)) != -1:
        out.append((mapping[k], mapping[min(k + len(needle), len(mapping)) - 1] + 1))
        start = k + 1
    return out


MATH_RE = re.compile(r"\$\$.+?\$\$|\$[^$\n]+?\$")


def _without_math(text: str) -> str:
    """Text ohne $…$-Formeln – LaTeX-Befehle wie \\begin{pmatrix} sollen nicht als Treffer zählen."""
    return MATH_RE.sub(" ", text)


def highlight_line(line: str, needles: list[str]) -> str:
    """Wie highlight, aber Formeln bleiben unmarkiert und werden im Browser mit KaTeX gesetzt."""
    if "$" not in line:
        return highlight(line, needles)
    out, pos = [], 0
    for m in MATH_RE.finditer(line):
        out.append(highlight(line[pos:m.start()], needles, shorten=False))
        tex = m.group(0).strip("$")
        out.append(f'<span class="math inline">{escape(tex)}</span>')
        pos = m.end()
    out.append(highlight(line[pos:], needles, shorten=False))
    return "".join(out)


def highlight(text: str, needles: list[str], shorten: bool = True) -> str:
    """HTML mit <mark> um alle Treffer; lange Texte auf ein Fenster um den ersten Treffer gekürzt."""
    spans = sorted({s for n in needles for s in _positions(text, n)})
    if shorten and spans and len(text) > SNIPPET_CHARS:
        first = spans[0][0]
        lo = max(0, first - SNIPPET_CHARS // 3)
        hi = min(len(text), lo + SNIPPET_CHARS)
        prefix, suffix = ("… " if lo else ""), (" …" if hi < len(text) else "")
        text = text[lo:hi]
        spans = [(a - lo, b - lo) for a, b in spans if a >= lo and b <= hi]
    else:
        prefix = suffix = ""
    out, pos = [], 0
    for a, b in spans:
        if a < pos:
            continue
        out.append(escape(text[pos:a]))
        out.append(f"<mark>{escape(text[a:b])}</mark>")
        pos = b
    out.append(escape(text[pos:]))
    return escape(prefix) + "".join(out) + escape(suffix)


def _sections(markdown: str) -> list[tuple[str, list[str]]]:
    """(Überschriften-Pfad, Zeilen) je Abschnitt; Überschriften gehören zu ihrem Abschnitt."""
    sections: list[tuple[str, list[str]]] = []
    path: dict[int, str] = {}
    current: list[str] = []
    title = ""
    in_fence = False
    for line in markdown.splitlines():
        stripped = re.sub(r"^\s*(?:>\s*)*", "", line)
        if stripped.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue  # Diagramm-Quelltext nicht durchsuchen
        m = re.match(r"^(#{1,3})\s+(.*)$", line)
        if m:
            if current:
                sections.append((title, current))
            level = len(m.group(1))
            path = {k: v for k, v in path.items() if k < level}
            path[level] = _plain(m.group(2))
            title = " › ".join(v for k, v in sorted(path.items()) if k > 1) or path.get(1, "")
            current = [line]
        elif line.strip():
            current.append(line)
    if current:
        sections.append((title, current))
    return sections


def search_notes(markdown: str, needles: list[str]) -> list[dict]:
    hits = []
    for title, lines in _sections(markdown):
        if not all(n in fold(_without_math("\n".join(lines))) for n in needles):
            continue
        body = lines[1:] if re.match(r"^#{1,3}\s", lines[0]) else lines  # Überschrift steht schon darüber
        matching = [_plain(l) for l in body if any(n in fold(_without_math(l)) for n in needles)]
        matching = [l for l in matching if l][:MAX_LINES_PER_SECTION]
        hits.append({"section": title, "lines": [highlight_line(l, needles) for l in matching]})
    return hits


def search_transcript(segments: list[dict], needles: list[str]) -> list[dict]:
    hits = []
    for block in merge_segments(segments):
        if all(n in fold(block["text"]) for n in needles):
            hits.append({"seconds": int(block["start"]), "ts": fmt_ts(block["start"]),
                         "text": highlight(block["text"], needles)})
            if len(hits) >= MAX_TRANSCRIPT_HITS:
                break
    return hits
