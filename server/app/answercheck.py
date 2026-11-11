"""Antworten beim Lernen von Claude prüfen lassen (sofort, nicht über die Batch-API).

- Karteikarten: getippte oder diktierte Antwort → Bewertung, was fehlt, Rückfrage zum Hinterfragen.
- Aufgaben: Foto des handschriftlichen Rechenwegs → Bewertung und wo der erste Fehler steckt.

Der vorgeschlagene Knopf ergibt sich fest aus der Bewertung (falsch → Nochmal, teilweise →
Schwer, richtig → Gut); „Leicht“ entscheidest du selbst.
"""

import base64
import io
import json
from html import escape

BEWERTUNGEN = ("richtig", "teilweise", "falsch")
VORSCHLAG = {"richtig": 3, "teilweise": 2, "falsch": 1}
MAX_IMAGE_SIDE = 1568      # größere Fotos verkleinern (spart Tokens, reicht für Handschrift)
MAX_IMAGE_BYTES = 8 << 20  # nach dem Base64-Dekodieren

TEXT_SYSTEM = """\
Du prüfst die Antwort einer/eines Studierenden auf eine Lernkarte. Du bekommst Frage, \
Musterantwort und die Antwort. Die Antwort wurde getippt oder diktiert – ignoriere Tipp-, \
Rechtschreib- und typische Diktierfehler (falsch erkannte Wörter, fehlende Satzzeichen, \
ausgeschriebene Formeln wie „lambda mal v“).

Bewerte den Inhalt, nicht die Formulierung. Andere korrekte Formulierungen, Beispiele oder \
zusätzliche richtige Details zählen als richtig.
- "richtig": der Kern der Musterantwort ist enthalten und nichts Wesentliches ist falsch.
- "teilweise": die Richtung stimmt, aber ein wesentlicher Teil fehlt oder ist ungenau.
- "falsch": der Kern fehlt oder die Antwort enthält einen wesentlichen fachlichen Fehler.

rueckmeldung: 1–3 Sätze, direkt mit „du“. Bei Fehlern: was genau fehlt oder falsch ist und \
warum. Bei richtigen Antworten: kurze Bestätigung, ggf. ein Punkt, der die Antwort noch \
präziser machen würde. Kein Lob-Vorspann.
fehlt: die fehlenden oder falschen Punkte als kurze Stichpunkte (leer, wenn nichts fehlt).
rueckfrage: EINE Rückfrage, die prüft, ob das Verständnis über das Auswendiggelernte \
hinausgeht – z. B. „Warum …?“, „Was wäre, wenn …?“, ein Gegenbeispiel oder eine Anwendung. In \
1–3 Sätzen beantwortbar, nicht schon durch die Musterantwort beantwortet.
rueckfrage_erwartung: was eine gute Antwort auf die Rückfrage enthalten sollte (1–2 Sätze).

Schreibe auf Deutsch; Formeln als LaTeX in $…$."""

FOLLOWUP_SYSTEM = """\
Du hast einer/einem Studierenden zu einer Lernkarte eine Rückfrage gestellt, um das \
Verständnis zu hinterfragen. Du bekommst Karte, Rückfrage, die erwartete Antwort und die \
Antwort darauf (getippt oder diktiert – ignoriere Tipp- und Diktierfehler). Bewerte den \
Inhalt wie zuvor ("richtig", "teilweise", "falsch") und erkläre in rueckmeldung (1–3 Sätze, \
mit „du“), was stimmt und was fehlt – bei Fehlern mit der richtigen Erklärung. fehlt: \
Stichpunkte. rueckfrage und rueckfrage_erwartung: leere Strings. Deutsch, Formeln in $…$."""

PHOTO_SYSTEM = """\
Du prüfst den handschriftlichen Rechenweg einer/eines Studierenden zu einer Übungsaufgabe \
(Foto). Du bekommst Aufgabe, Musterlösung und Endergebnis.

Lies den Rechenweg Schritt für Schritt. Ein anderer korrekter Lösungsweg zählt genauso. \
- "richtig": Weg und Ergebnis stimmen (kleine Schreibfehler ohne Folgen sind egal).
- "teilweise": der Ansatz stimmt, aber ein Rechenfehler oder eine Lücke führt zu einem \
falschen oder unvollständigen Ergebnis.
- "falsch": falscher Ansatz oder keine verwertbare Lösung.
- "unleserlich": das Foto lässt sich nicht sicher lesen (unscharf, abgeschnitten, keine \
Rechnung zu sehen) – dann sag in rueckmeldung, was fehlt, und rate nichts.

fehler: wo der ERSTE Fehler steckt (welcher Schritt, was dort richtig wäre) – leer, wenn \
alles stimmt. rueckmeldung: 1–3 Sätze mit „du“, was gut ist und was zu tun ist. fehlt: \
fehlende Schritte als Stichpunkte. Deutsch, Formeln als LaTeX in $…$."""


def _schema(with_followup: bool, photo: bool) -> dict:
    props: dict = {
        "bewertung": {"type": "string", "enum": list(BEWERTUNGEN) + (["unleserlich"] if photo else [])},
        "rueckmeldung": {"type": "string"},
        "fehlt": {"type": "array", "items": {"type": "string"}},
    }
    if photo:
        props["fehler"] = {"type": "string"}
    if with_followup:
        props["rueckfrage"] = {"type": "string"}
        props["rueckfrage_erwartung"] = {"type": "string"}
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


def _params(model: str, effort: str, max_tokens: int, system: str, content, schema: dict) -> dict:
    return {
        "model": model,
        "max_tokens": max_tokens,
        "thinking": {"type": "adaptive"},
        "output_config": {"effort": effort, "format": {"type": "json_schema", "schema": schema}},
        "system": system,
        "messages": [{"role": "user", "content": content}],
    }


def text_request(*, model: str, effort: str, max_tokens: int, question: str, reference: str,
                 answer: str) -> dict:
    content = (f"<frage>\n{escape(question, quote=False)}\n</frage>\n"
               f"<musterantwort>\n{escape(reference, quote=False)}\n</musterantwort>\n"
               f"<antwort>\n{escape(answer, quote=False)}\n</antwort>\n\nPrüfe die Antwort.")
    return _params(model, effort, max_tokens, TEXT_SYSTEM, content, _schema(True, False))


def followup_request(*, model: str, effort: str, max_tokens: int, question: str, reference: str,
                     followup: str, expectation: str, answer: str) -> dict:
    content = (f"<karte>\nFrage: {escape(question, quote=False)}\n"
               f"Musterantwort: {escape(reference, quote=False)}\n</karte>\n"
               f"<rueckfrage>\n{escape(followup, quote=False)}\n</rueckfrage>\n"
               f"<erwartung>\n{escape(expectation, quote=False)}\n</erwartung>\n"
               f"<antwort>\n{escape(answer, quote=False)}\n</antwort>\n\nPrüfe die Antwort auf die Rückfrage.")
    return _params(model, effort, max_tokens, FOLLOWUP_SYSTEM, content, _schema(False, False))


def photo_request(*, model: str, effort: str, max_tokens: int, task: str, solution: str, result: str,
                  image_b64: str) -> dict:
    content = [
        {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": image_b64}},
        {"type": "text", "text": (f"<aufgabe>\n{escape(task, quote=False)}\n</aufgabe>\n"
                                  f"<musterloesung>\n{escape(solution, quote=False)}\n</musterloesung>\n"
                                  f"<ergebnis>{escape(result, quote=False)}</ergebnis>\n\n"
                                  "Prüfe den Rechenweg auf dem Foto.")},
    ]
    return _params(model, effort, max_tokens, PHOTO_SYSTEM, content, _schema(False, True))


def prepare_image(data_url: str) -> tuple[str, int]:
    """Data-URL bzw. Base64 → verkleinertes JPEG (Base64) und geschätzte Bild-Tokens.

    Der Browser schickt das Foto meist schon verkleinert; hier wird es zur Sicherheit noch
    einmal geprüft, gedreht (EXIF) und als JPEG neu kodiert.
    """
    from PIL import Image, ImageOps

    raw_b64 = data_url.split(",", 1)[1] if data_url.startswith("data:") else data_url
    try:
        raw = base64.b64decode(raw_b64, validate=True)
    except ValueError as e:
        raise ValueError("Das Foto ließ sich nicht lesen.") from e
    if len(raw) > MAX_IMAGE_BYTES:
        raise ValueError("Das Foto ist zu groß (höchstens 8 MB).")
    try:
        img = ImageOps.exif_transpose(Image.open(io.BytesIO(raw)))
    except Exception as e:  # kein Bild bzw. unbekanntes Format
        raise ValueError("Das Foto ließ sich nicht lesen (bitte als JPEG oder PNG).") from e
    img = img.convert("RGB")
    img.thumbnail((MAX_IMAGE_SIDE, MAX_IMAGE_SIDE))
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=85)
    tokens = img.width * img.height // 750 + 50
    return base64.standard_b64encode(out.getvalue()).decode("ascii"), tokens


def estimate_tokens(params: dict, image_tokens: int = 0) -> int:
    """Grobe Schätzung der Input-Tokens für die Budgetprüfung (ohne zusätzlichen API-Aufruf)."""
    content = params["messages"][0]["content"]
    text = content if isinstance(content, str) else " ".join(b.get("text", "") for b in content)
    return (len(params["system"]) + len(text)) // 3 + 50 + image_tokens


def parse(text: str) -> dict:
    data = json.loads(text)
    bewertung = data.get("bewertung")
    if bewertung not in BEWERTUNGEN + ("unleserlich",):
        raise ValueError(f"Unbekannte Bewertung {bewertung!r}")
    return {
        "bewertung": bewertung,
        "rueckmeldung": (data.get("rueckmeldung") or "").strip(),
        "fehlt": [f.strip() for f in data.get("fehlt") or [] if f and f.strip()],
        "fehler": (data.get("fehler") or "").strip(),
        "rueckfrage": (data.get("rueckfrage") or "").strip(),
        "rueckfrage_erwartung": (data.get("rueckfrage_erwartung") or "").strip(),
        "vorschlag": VORSCHLAG.get(bewertung),
    }
