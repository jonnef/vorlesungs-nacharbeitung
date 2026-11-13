import json
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

# Vor dem Import der App: Daten in ein temporäres Verzeichnis, Token setzen, kein Auto-Polling.
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="vorlesung-test-")
os.environ["API_TOKEN"] = "test-token"
os.environ["POLL_INTERVAL_SEC"] = "3600"
os.environ["MONTHLY_BUDGET_USD"] = "5"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class FakeBatches:
    def __init__(self, parent):
        self.parent = parent
        self.created = []

    def create(self, requests):
        self.created.append(requests)
        return SimpleNamespace(id=f"msgbatch_{len(self.created)}")

    def retrieve(self, batch_id):
        return SimpleNamespace(processing_status="ended" if self.parent.finished else "in_progress")

    def results(self, batch_id):
        idx = int(batch_id.split("_")[1]) - 1
        request = self.created[idx][0]
        is_glossary = "format" in request["params"].get("output_config", {})
        system = request["params"]["system"]
        is_exam = "Klausurvorbereitung" in system
        is_hints = "AUSDRÜCKLICH über die Klausur" in system
        is_cardcheck = "räumst die Lernkarten" in system
        is_cards = "Wiederholung in wachsenden Abständen" in system
        is_conceptmap = "Concept Map" in system
        text = (self.parent.cardcheck_answer(request["params"]) if is_cardcheck
                else self.parent.conceptmap_json if is_conceptmap else self.parent.cards_json if is_cards
                else self.parent.hints_json if is_hints else self.parent.glossary_json if is_glossary
                else self.parent.exam_md if is_exam else self.parent.notes)
        msg = SimpleNamespace(
            model="claude-opus-5",
            stop_reason=self.parent.stop_reason,
            content=[
                SimpleNamespace(type="thinking", thinking=""),
                SimpleNamespace(type="text", text=text),
            ],
            usage=SimpleNamespace(input_tokens=10_000, output_tokens=4_000,
                                  cache_creation_input_tokens=0, cache_read_input_tokens=0),
        )
        yield SimpleNamespace(custom_id=request["custom_id"], result=SimpleNamespace(type="succeeded", message=msg))


class FakeClient:
    def __init__(self):
        self.finished = False
        self.stop_reason = "end_turn"
        self.notes = "# Notizen\n- Punkt [00:00:10] [Skript S. 1]\n- Falsch [09:00:00] [Skript S. 99]"
        self.glossary_json = json.dumps({"eintraege": [
            {"begriff": "Eigenwert", "art": "Begriff", "definition": "Skalar $\\lambda$ mit $Av = \\lambda v$.",
             "formel": "Av = \\lambda v", "zeitstempel": ["00:00:10", "09:00:00"], "seiten": ["Skript S. 1", "Skript S. 99"]},
            {"begriff": "Ähnlichkeit", "art": "Satz", "definition": "Ähnliche Matrizen haben dieselben Eigenwerte.",
             "formel": "", "zeitstempel": [], "seiten": []},
        ]})
        self.exam_md = ("# Klausurvorbereitung – Lineare Algebra\n\n## Vom Dozenten ausdrücklich genannt\n"
                        "- Eigenwerte kommen dran [V1 00:00:40]\n- Falsch [V9 00:00:10] und [V1 05:00:00]\n\n"
                        "## Checkliste\n- [ ] Eigenwerte üben")
        self.hints_json = json.dumps({"hinweise": [
            {"art": "klausurrelevant", "thema": "Klausur", "zitat": "Das kommt garantiert in der Klausur.",
             "zeitstempel": "00:00:40", "seiten": ["Skript S. 1", "Skript S. 99"], "erlaeuterung": "Wird geprüft."},
            {"art": "typischer_fehler", "thema": "Erfunden", "zitat": "Das hat der Dozent so nie gesagt.",
             "zeitstempel": "00:00:08", "seiten": [], "erlaeuterung": ""},
            {"art": "klausurrelevant", "thema": "Zu spät", "zitat": "Heute geht es um Eigenwerte.",
             "zeitstempel": "05:00:00", "seiten": [], "erlaeuterung": ""},
        ]})
        self.cards_json = json.dumps({"eintraege": [
            {"art": "karte", "thema": "Eigenwerte", "taschenrechner": False,
             "varianten": [{"vorderseite": "Was ist ein Eigenwert?", "rueckseite": "Ein $\\lambda$ mit $Av = \\lambda v$.",
                            "ergebnis": ""}, {"vorderseite": "Überzählig", "rueckseite": "x", "ergebnis": ""}],
             "zeitstempel": ["00:00:10", "09:00:00"], "seiten": ["Skript S. 1", "Skript S. 99"]},
            {"art": "aufgabe", "thema": "Eigenwerte berechnen", "taschenrechner": False,
             "varianten": [{"vorderseite": f"Eigenwerte von $\\mathrm{{diag}}({a},{b})$?",
                            "rueckseite": "Diagonalmatrix: Eigenwerte stehen auf der Diagonale.",
                            "ergebnis": f"$\\lambda = {a}, {b}$"} for a, b in ((1, 2), (3, 4), (5, 6))],
             "zeitstempel": [], "seiten": []},
            {"art": "aufgabe", "thema": "Logarithmus", "taschenrechner": True,
             "varianten": [{"vorderseite": "Berechne $\\ln 7$.", "rueckseite": "Mit dem Taschenrechner.",
                            "ergebnis": "1,9459"}], "zeitstempel": [], "seiten": []},
            {"art": "karte", "thema": "Leer", "taschenrechner": False, "varianten": [], "zeitstempel": [], "seiten": []},
        ]})
        self.conceptmap_json = json.dumps({
            "knoten": [{"begriff": "Eigenwert", "gruppe": "Eigenwerte"}, {"begriff": "Erfunden", "gruppe": "X"}],
            "kanten": [
                {"von": "Ähnlichkeit", "nach": "eigenwert", "art": "verwendet", "beschriftung": "erhält die"},
                {"von": "Ähnlichkeit", "nach": "Eigenwert", "art": "verwandt", "beschriftung": "doppelt"},
                {"von": "Eigenwert", "nach": "Eigenwert", "art": "verwandt", "beschriftung": "Schleife"},
                {"von": "Eigenwert", "nach": "Erfunden", "art": "teil", "beschriftung": "unbekannt"},
            ]})
        self.counted = []
        self.messages = SimpleNamespace(count_tokens=self._count, batches=FakeBatches(self), create=self._create)
        self.created = []  # Sofort-Aufrufe (Antwortprüfung)
        self.check_stop_reason = "end_turn"

    def with_options(self, **_):
        return self

    def _create(self, **params):
        """Antwortprüfung: liefert je nach Prompt eine passende JSON-Bewertung."""
        self.created.append(params)
        system = params["system"]
        if "handschriftlichen Rechenweg" in system:
            data = {"bewertung": "teilweise", "antwort": "Du hast $(2-\\lambda)^2 - 1$ angesetzt, aber $\\lambda_2$ ist falsch.",
                    "fehlt": ["Probe"], "fehler": "Zeile 3: Vorzeichenfehler.", "musterantwort_hinweis": ""}
        elif len(params["messages"]) == 1:
            data = {"bewertung": "falsch", "antwort": "Es fehlt $v \\neq 0$.", "fehlt": ["$v \\neq 0$"],
                    "verstanden": "Ein Skalar mit Av = λv.", "musterantwort_hinweis": ""}
        else:
            data = {"bewertung": "richtig", "antwort": "Du hast recht, das war gemeint.", "fehlt": [],
                    "verstanden": "", "musterantwort_hinweis": "Die Musterantwort könnte v ≠ 0 betonen."}
        return SimpleNamespace(
            model=params["model"], stop_reason=self.check_stop_reason,
            content=[SimpleNamespace(type="thinking", thinking=""), SimpleNamespace(type="text", text=json.dumps(data))],
            usage=SimpleNamespace(input_tokens=800, output_tokens=300, cache_creation_input_tokens=0,
                                  cache_read_input_tokens=0))

    @staticmethod
    def cardcheck_answer(params):
        """Sortiert Karten mit „Anmeldung“ aus – plus eine unbekannte ID, die verworfen werden muss."""
        import re
        content = params["messages"][0]["content"]
        flagged = [{"id": int(i), "grund": "organisatorisch", "begruendung": "Termin, kein Fachinhalt."}
                   for i, front in re.findall(r'<karte id="(\d+)"[^>]*>\nVorderseite: ([^\n]*)', content)
                   if "Anmeldung" in front]
        return json.dumps({"aussortieren": flagged + [{"id": 99999, "grund": "organisatorisch", "begruendung": ""}]})

    def _count(self, **params):
        self.counted.append(params)
        text = params["system"] + params["messages"][0]["content"]
        return SimpleNamespace(input_tokens=len(text) // 3)


@pytest.fixture
def fake_client():
    return FakeClient()


@pytest.fixture
def sample_pdf(tmp_path) -> Path:
    from reportlab.pdfgen import canvas

    path = tmp_path / "Skript.pdf"
    c = canvas.Canvas(str(path))
    for text in ["Eigenwerte und Eigenvektoren einer Matrix", "Fourier-Reihen und Konvergenz"]:
        c.drawString(72, 720, text)
        c.showPage()
    c.save()
    return path


SEGMENTS = [
    {"start": 0.0, "end": 8.0, "text": "Heute geht es um Eigenwerte."},
    {"start": 8.0, "end": 20.0, "text": "Ein Eigenvektor einer Matrix wird nur gestreckt."},
    {"start": 40.0, "end": 55.0, "text": "Das kommt garantiert in der Klausur."},
]
