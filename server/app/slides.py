"""Folienbilder: eine Seite aus dem Dozenten-PDF als PNG (für die Seitenangaben in den Notizen).

Gerendert wird beim ersten Aufruf und dann als Datei zwischengespeichert, damit der Pi jede
Seite nur einmal rechnen muss.
"""

import threading
from pathlib import Path

import pypdfium2 as pdfium

WIDTH = 1400  # Pixel – scharf genug für Formeln und Grafiken, klein genug fürs Handy
_lock = threading.Lock()  # pdfium ist nicht threadsicher


def text_png(title: str, text: str, cache: Path) -> Path:
    """Ersatzfolie aus dem Seitentext – nur für die Vorschau mit Beispieldaten (dort gibt es kein PDF)."""
    from PIL import Image, ImageDraw, ImageFont
    import textwrap

    if cache.exists():
        return cache
    cache.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (WIDTH, WIDTH * 9 // 16), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle([0, 0, WIDTH, 110], fill="#1e3a8a")
    draw.text((60, 30), title, fill="white", font=ImageFont.load_default(size=48))
    y = 170
    for line in textwrap.wrap(text, 60):
        draw.text((60, y), line, fill="#1c1917", font=ImageFont.load_default(size=36))
        y += 56
    image.save(cache, format="PNG", optimize=True)
    return cache


def page_png(pdf: Path, page_index: int, cache: Path) -> Path:
    """Pfad zum PNG der Seite (0-basiert); erzeugt es bei Bedarf."""
    if cache.exists():
        return cache
    cache.parent.mkdir(parents=True, exist_ok=True)
    with _lock:
        doc = pdfium.PdfDocument(str(pdf))
        try:
            page = doc[page_index]
            scale = WIDTH / page.get_width()
            image = page.render(scale=scale).to_pil()
        finally:
            doc.close()
    tmp = cache.with_suffix(".tmp")
    image.save(tmp, format="PNG", optimize=True)
    tmp.replace(cache)
    return cache
