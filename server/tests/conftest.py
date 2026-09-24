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
        custom_id = self.created[idx][0]["custom_id"]
        msg = SimpleNamespace(
            model="claude-opus-5",
            stop_reason=self.parent.stop_reason,
            content=[
                SimpleNamespace(type="thinking", thinking=""),
                SimpleNamespace(type="text", text=self.parent.notes),
            ],
            usage=SimpleNamespace(input_tokens=10_000, output_tokens=4_000,
                                  cache_creation_input_tokens=0, cache_read_input_tokens=0),
        )
        yield SimpleNamespace(custom_id=custom_id, result=SimpleNamespace(type="succeeded", message=msg))


class FakeClient:
    def __init__(self):
        self.finished = False
        self.stop_reason = "end_turn"
        self.notes = "# Notizen\n- Punkt [00:00:10] [Skript S. 1]\n- Falsch [09:00:00] [Skript S. 99]"
        self.counted = []
        self.messages = SimpleNamespace(count_tokens=self._count, batches=FakeBatches(self))

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
