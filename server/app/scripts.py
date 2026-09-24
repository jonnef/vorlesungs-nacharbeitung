"""Dozenten-Skripte: seitenweise Textextraktion aus PDFs."""

import re
from pathlib import Path

from pypdf import PdfReader


def extract_pages(path: Path) -> list[tuple[int, str, str]]:
    """Liefert (Seitenindex, Seitenbezeichnung, Text) je PDF-Seite.

    Die Bezeichnung ist die im PDF hinterlegte Seitennummer (z. B. "iv" oder "12"),
    damit Zitate zur aufgedruckten Seitenzahl passen; ohne Labels die fortlaufende Nummer.
    """
    reader = PdfReader(str(path))
    labels = reader.page_labels if reader.page_labels else []
    pages = []
    for i, page in enumerate(reader.pages):
        try:
            text = page.extract_text() or ""
        except Exception:  # einzelne kaputte Seiten sollen nicht das ganze Skript verhindern
            text = ""
        label = labels[i] if i < len(labels) and labels[i] else str(i + 1)
        pages.append((i, label, clean_text(text)))
    return pages


def clean_text(text: str) -> str:
    text = text.replace("\x00", "")
    text = re.sub(r"-\n(?=[a-zäöüß])", "", text)  # Silbentrennung am Zeilenende
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{2,}", "\n", text)
    return text.strip()


def make_kuerzel(filename: str, taken: set[str]) -> str:
    """Kurzes, eindeutiges Kürzel pro Skript, das Claude in Zitaten verwendet: [Kürzel S. 12]."""
    stem = Path(filename).stem
    base = re.sub(r"[^\w\-]+", "_", stem).strip("_")[:24] or "Skript"
    kuerzel, n = base, 2
    while kuerzel in taken:
        kuerzel = f"{base}_{n}"
        n += 1
    return kuerzel
