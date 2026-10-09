"""Markdown → HTML für Notizen und Klausurvorbereitung.

Neben CommonMark (Tabellen, $…$-Formeln, Checklisten) versteht der Renderer Callouts in
Obsidian-Schreibweise, die als aufklappbare Kästen erscheinen:

    > [!example]- Beispiel: Basiswechsel
    > Inhalt …

„-“ = zugeklappt, „+“ oder nichts = aufgeklappt. ```mermaid-Blöcke werden im Browser zu
Diagrammen. Zeitstempel [hh:mm:ss] und Seitenangaben [Kürzel S. 12] werden hervorgehoben;
Seitenangaben öffnen die Folie.
"""

import re
from html import escape

from markdown_it import MarkdownIt
from mdit_py_plugins.dollarmath import dollarmath_plugin
from mdit_py_plugins.tasklists import tasklists_plugin

from .prompt import PAGE_RE, TS_RE

# CommonMark wie in üblichen Markdown-Editoren (Listen ohne Leerzeile, 2er-Einrückung),
# plus Tabellen und $…$/$$…$$-Formeln (im Browser mit KaTeX gesetzt). Kein Roh-HTML.
MARKDOWN = (
    MarkdownIt("commonmark", {"html": False})
    .enable(["table", "strikethrough"])
    .use(dollarmath_plugin, double_inline=True)
    .use(tasklists_plugin)  # "- [ ] …" in Checklisten
)

CALLOUT_RE = re.compile(r"^>\s*\[!([A-Za-z]+)\]([+-]?)[ \t]*(.*)$")
FENCE_RE = re.compile(r"^\s*(```|~~~)")

# Typ → (Standardtitel, Symbol)
CALLOUTS = {
    "example": ("Beispiel", "✎"),
    "solution": ("Musterlösung", "✓"),
    "answer": ("Antwort", "✓"),
    "proof": ("Herleitung", "∴"),
    "diagram": ("Diagramm", "◇"),
    "question": ("Frage", "?"),
    "tip": ("Tipp", "💡"),
    "hint": ("Hinweis", "💡"),
    "note": ("Notiz", "ℹ"),
    "info": ("Info", "ℹ"),
    "warning": ("Achtung", "⚠"),
    "important": ("Wichtig", "!"),
}


def _split(markdown: str) -> list[tuple[str, object]]:
    """Zerlegt in ("md", text) und ("callout", (typ, faltung, titel, innen)) – Code-Blöcke bleiben ganz."""
    parts: list[tuple[str, object]] = []
    plain: list[str] = []
    lines = markdown.splitlines()
    i, in_fence = 0, False
    while i < len(lines):
        line = lines[i]
        if FENCE_RE.match(line):
            in_fence = not in_fence
        m = None if in_fence else CALLOUT_RE.match(line)
        if not m:
            plain.append(line)
            i += 1
            continue
        if plain:
            parts.append(("md", "\n".join(plain)))
            plain = []
        inner = []
        i += 1
        while i < len(lines) and lines[i].startswith(">"):
            inner.append(re.sub(r"^> ?", "", lines[i]))
            i += 1
        parts.append(("callout", (m.group(1).lower(), m.group(2), m.group(3).strip(), "\n".join(inner))))
    if plain:
        parts.append(("md", "\n".join(plain)))
    return parts


def _render_blocks(markdown: str) -> str:
    out = []
    for kind, value in _split(markdown):
        if kind == "md":
            out.append(MARKDOWN.render(value))
            continue
        ctype, fold, title, inner = value
        default_title, icon = CALLOUTS.get(ctype, (ctype.capitalize(), "•"))
        title_html = MARKDOWN.renderInline(title) if title else escape(default_title)
        is_open = "" if fold == "-" else " open"
        out.append(
            f'<details class="callout callout-{escape(ctype)}"{is_open}>'
            f'<summary><span class="callout-icon" aria-hidden="true">{icon}</span>{title_html}</summary>'
            f'<div class="callout-body">{_render_blocks(inner)}</div></details>\n'
        )
    return "".join(out)


def render_notes(markdown: str) -> str:
    """Markdown → HTML; Zeitstempel und Seitenangaben werden hervorgehoben."""
    html = _render_blocks(markdown)
    html = TS_RE.sub(r'<span class="ts">[\1]</span>', html)
    return PAGE_RE.sub(
        lambda m: f'<button type="button" class="page" data-k="{escape(m.group(1))}" data-p="{escape(m.group(2))}"'
                  f' title="Folie anzeigen">[{m.group(1)} S. {m.group(2)}]</button>',
        html,
    )


def render_inline(text: str) -> str:
    """Einzeilige Markdown-Texte (Glossar-Definitionen) inkl. $…$-Formeln."""
    return MARKDOWN.renderInline(text)
