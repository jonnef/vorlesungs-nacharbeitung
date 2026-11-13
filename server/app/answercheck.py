"""Antworten beim Lernen mit Claude besprechen (sofort, nicht über die Batch-API).

- Karteikarten: Deine Antwort (getippt, diktiert oder gesprochen) ist die erste Nachricht eines
  kurzen Gesprächs. Claude vergleicht sie mit der Musterantwort; danach kannst du widersprechen
  oder nachhaken, und Claude passt die Bewertung an, wenn du recht hast.
- Aufgaben: Foto des handschriftlichen Rechenwegs → Bewertung und wo der erste Fehler steckt;
  danach lässt sich ebenfalls darüber diskutieren.

Der Verlauf wird nicht gespeichert: Der Browser schickt ihn bei jeder Nachricht mit.
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
MAX_MESSAGES = 20          # Länge eines Gesprächs zu einer Karte
MAX_MESSAGE_CHARS = 4000
PHOTO_PLACEHOLDER = "[Foto meines Rechenwegs]"

CHAT_SYSTEM = """\
Du besprichst mit einer/einem Studierenden die Antwort auf eine Lernkarte. Du kennst Frage und \
Musterantwort. Die Nachrichten der/des Studierenden sind oft gesprochen oder diktiert: Ignoriere \
Füllwörter („ähm“, „also“, „sozusagen“), Wiederholungen, Versprecher, Selbstkorrekturen (es gilt \
die korrigierte Fassung), Tipp- und Spracherkennungsfehler (falsch erkannte Wörter, ausgesprochene \
Formeln wie „lambda mal v“).

Erste Nachricht = die Antwort auf die Karte. Vergleiche sie inhaltlich mit der Musterantwort: was \
übereinstimmt, was fehlt, was abweicht oder falsch ist. Andere korrekte Formulierungen, Beispiele \
und zusätzliche richtige Details zählen als richtig.
- "richtig": der Kern der Musterantwort ist enthalten, nichts Wesentliches ist falsch.
- "teilweise": die Richtung stimmt, aber ein wesentlicher Teil fehlt oder ist ungenau.
- "falsch": der Kern fehlt oder es gibt einen wesentlichen fachlichen Fehler.

Spätere Nachrichten = Diskussion über die Antwort und die Musterantwort. Geh direkt auf das \
Argument bzw. die Frage ein. Hat die/der Studierende recht (z. B. etwas war doch enthalten, nur \
anders formuliert), sag das klar und passe die Bewertung an; hat sie/er nicht recht, erkläre \
sachlich, warum. Stelle keine neuen Prüfungsfragen und lenke nicht auf andere Themen.

Ist die Musterantwort selbst ungenau, unvollständig oder falsch, sag das offen in \
musterantwort_hinweis (sonst leerer String).

Felder:
- bewertung: aktuelle Gesamtbewertung der Antwort auf die Karte (nach allem Besprochenen).
- antwort: deine Nachricht, 1–5 Sätze, direkt mit „du“, kein Lob-Vorspann; Markdown erlaubt.
- fehlt: noch fehlende oder falsche Punkte als kurze Stichpunkte (leer, wenn nichts fehlt).
- verstanden: die letzte Nachricht der/des Studierenden bereinigt (ohne Füllwörter, Versprecher \
und Erkennungsfehler, sonst sinngemäß unverändert); leerer String, wenn sie schon sauber war.
- musterantwort_hinweis: siehe oben.

Deutsch; Formeln als LaTeX in $…$."""

PHOTO_SYSTEM = """\
Du prüfst den handschriftlichen Rechenweg einer/eines Studierenden zu einer Übungsaufgabe \
(Foto). Du bekommst Aufgabe, Musterlösung und Endergebnis.

Lies den Rechenweg Schritt für Schritt. Ein anderer korrekter Lösungsweg zählt genauso.
- "richtig": Weg und Ergebnis stimmen (kleine Schreibfehler ohne Folgen sind egal).
- "teilweise": der Ansatz stimmt, aber ein Rechenfehler oder eine Lücke führt zu einem \
falschen oder unvollständigen Ergebnis.
- "falsch": falscher Ansatz oder keine verwertbare Lösung.
- "unleserlich": das Foto lässt sich nicht sicher lesen (unscharf, abgeschnitten, keine \
Rechnung zu sehen) – dann sag in antwort, was fehlt, und rate nichts.

antwort: 1–4 Sätze mit „du“: was gut ist und was zu tun ist. Beschreibe dabei kurz, was du auf \
dem Foto gelesen hast (z. B. „Du hast … angesetzt und … erhalten“), damit man später darüber \
sprechen kann. fehler: wo der ERSTE Fehler steckt (welcher Schritt, was dort richtig wäre) – \
leer, wenn alles stimmt. fehlt: fehlende Schritte als Stichpunkte. musterantwort_hinweis: nur \
wenn die Musterlösung selbst fehlerhaft ist, sonst leer. Deutsch, Formeln als LaTeX in $…$."""


def _schema(photo: bool) -> dict:
    props: dict = {
        "bewertung": {"type": "string", "enum": list(BEWERTUNGEN) + (["unleserlich"] if photo else [])},
        "antwort": {"type": "string"},
        "fehlt": {"type": "array", "items": {"type": "string"}},
        "musterantwort_hinweis": {"type": "string"},
    }
    if photo:
        props["fehler"] = {"type": "string"}
    else:
        props["verstanden"] = {"type": "string"}
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


def _params(model: str, effort: str, max_tokens: int, system: str, messages: list, schema: dict) -> dict:
    return {
        "model": model,
        "max_tokens": max_tokens,
        "thinking": {"type": "adaptive"},
        "output_config": {"effort": effort, "format": {"type": "json_schema", "schema": schema}},
        "system": system,
        "messages": messages,
    }


def clean_history(history: list) -> list[dict]:
    """Prüft den vom Browser geschickten Verlauf: abwechselnd user/assistant, endet mit user."""
    if not isinstance(history, list) or not history:
        raise ValueError("Bitte zuerst eine Antwort eingeben.")
    if len(history) > MAX_MESSAGES:
        raise ValueError("Das Gespräch zu dieser Karte ist zu lang – bitte bewerten und weiterlernen.")
    out = []
    for i, m in enumerate(history):
        role = m.get("role") if isinstance(m, dict) else None
        text = str(m.get("text", "")).strip() if isinstance(m, dict) else ""
        if role != ("user" if i % 2 == 0 else "assistant"):
            raise ValueError("Ungültiger Gesprächsverlauf.")
        if not text:
            raise ValueError("Bitte zuerst eine Antwort eingeben.")
        if len(text) > MAX_MESSAGE_CHARS:
            raise ValueError(f"Eine Nachricht ist zu lang (höchstens {MAX_MESSAGE_CHARS} Zeichen).")
        out.append({"role": role, "text": text})
    if out[-1]["role"] != "user":
        raise ValueError("Ungültiger Gesprächsverlauf.")
    return out


def chat_request(*, model: str, effort: str, max_tokens: int, question: str, reference: str,
                 history: list[dict], photo_context: bool = False) -> dict:
    """`history`: bereinigter Verlauf (clean_history). Die Karte steht in der ersten Nachricht."""
    card = (f"<frage>\n{escape(question, quote=False)}\n</frage>\n"
            f"<musterantwort>\n{escape(reference, quote=False)}\n</musterantwort>\n")
    if photo_context:
        card += ("<hinweis>Die/der Studierende hat ein Foto des Rechenwegs geschickt; deine erste "
                 "Antwort unten beschreibt, was du darauf gelesen hast. Das Foto selbst liegt nicht "
                 "mehr vor.</hinweis>\n")
    messages = []
    for i, m in enumerate(history):
        text = escape(m["text"], quote=False)
        if i == 0:
            text = f"{card}<antwort>\n{text}\n</antwort>"
        messages.append({"role": m["role"], "content": text})
    return _params(model, effort, max_tokens, CHAT_SYSTEM, messages, _schema(False))


def photo_request(*, model: str, effort: str, max_tokens: int, task: str, solution: str, result: str,
                  image_b64: str) -> dict:
    content = [
        {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": image_b64}},
        {"type": "text", "text": (f"<aufgabe>\n{escape(task, quote=False)}\n</aufgabe>\n"
                                  f"<musterloesung>\n{escape(solution, quote=False)}\n</musterloesung>\n"
                                  f"<ergebnis>{escape(result, quote=False)}</ergebnis>\n\n"
                                  "Prüfe den Rechenweg auf dem Foto.")},
    ]
    return _params(model, effort, max_tokens, PHOTO_SYSTEM, [{"role": "user", "content": content}], _schema(True))


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
    chars = len(params["system"])
    for m in params["messages"]:
        c = m["content"]
        chars += len(c) if isinstance(c, str) else sum(len(b.get("text", "")) for b in c)
    return chars // 3 + 50 * len(params["messages"]) + image_tokens


def parse(text: str) -> dict:
    data = json.loads(text)
    bewertung = data.get("bewertung")
    if bewertung not in BEWERTUNGEN + ("unleserlich",):
        raise ValueError(f"Unbekannte Bewertung {bewertung!r}")
    return {
        "bewertung": bewertung,
        "antwort": (data.get("antwort") or "").strip(),
        "fehlt": [f.strip() for f in data.get("fehlt") or [] if f and f.strip()],
        "fehler": (data.get("fehler") or "").strip(),
        "verstanden": (data.get("verstanden") or "").strip(),
        "musterantwort_hinweis": (data.get("musterantwort_hinweis") or "").strip(),
        "vorschlag": VORSCHLAG.get(bewertung),
    }


def history_text(result: dict) -> str:
    """Wie eine Antwort von Claude im Verlauf für die nächste Nachricht wiedergegeben wird."""
    parts = [f"Bewertung: {result['bewertung']}", result["antwort"]]
    if result.get("fehler"):
        parts.append(f"Erster Fehler: {result['fehler']}")
    if result.get("fehlt"):
        parts.append("Fehlt: " + "; ".join(result["fehlt"]))
    if result.get("musterantwort_hinweis"):
        parts.append(f"Zur Musterantwort: {result['musterantwort_hinweis']}")
    return "\n".join(p for p in parts if p)
