from types import SimpleNamespace

import pytest

from app import main, speech

from .test_api import client  # noqa: F401  (Fixture)
from .test_cards import _setup


class FakeWhisper:
    def __init__(self, text="Ähm also ein Eigenwert ist äh ein Skalar", duration=5.0):
        self.text, self.duration, self.calls = text, duration, []

    def transcribe(self, path, **kw):
        self.calls.append((path, kw))
        segments = (SimpleNamespace(text=t) for t in self.text.split("|"))
        return segments, SimpleNamespace(duration=self.duration)


@pytest.fixture
def fake_whisper(monkeypatch):
    fake = FakeWhisper()
    monkeypatch.setattr(speech, "_load", lambda name, threads: fake)
    return fake


def test_prompt_strips_formulas():
    p = speech.prompt_for(r"Warum gilt $\det(A - \lambda E) = 0$ für **Eigenwerte**?", "Eigenwerte")
    assert "$" not in p and "\\" not in p and "Eigenwerte" in p
    assert len(speech.prompt_for("x" * 2000)) == speech.PROMPT_CHARS


def test_transcribe_joins_segments(fake_whisper):
    fake_whisper.text = " Erster Teil. | Zweiter  Teil. "
    assert speech.transcribe("a.webm", model="small", threads=4, beam_size=1, prompt="P") == "Erster Teil. Zweiter Teil."
    _path, kw = fake_whisper.calls[-1]
    assert kw["language"] == "de" and kw["vad_filter"] and kw["initial_prompt"] == "P" and kw["beam_size"] == 1


def test_speech_endpoint(client, fake_client, sample_pdf, fake_whisper):
    _setup(client, fake_client, sample_pdf)
    card = next(c for c in main.service.list_cards() if c["kind"] == "karte")
    r = client.post(f"/lernen/{card['id']}/sprache", files={"audio": ("a.m4a", b"\x00" * 1000, "audio/mp4")})
    assert r.status_code == 200 and r.json() == {"text": "Ähm also ein Eigenwert ist äh ein Skalar"}
    path, kw = fake_whisper.calls[-1]
    assert path.endswith(".m4a") and "Was ist ein Eigenwert" in kw["initial_prompt"]

    # zu lange Aufnahme
    fake_whisper.duration = speech.MAX_SECONDS + 1
    r = client.post(f"/lernen/{card['id']}/sprache", files={"audio": ("a.webm", b"\x00" * 10, "audio/webm")})
    assert r.status_code == 400 and "zu lang" in r.json()["fehler"]

    assert client.post("/lernen/999999/sprache", files={"audio": ("a.webm", b"x", "audio/webm")}).status_code == 404


def test_speech_size_limit_and_missing_package(client, fake_client, sample_pdf, monkeypatch):
    _setup(client, fake_client, sample_pdf)
    card = next(c for c in main.service.list_cards() if c["kind"] == "karte")
    monkeypatch.setattr(speech, "MAX_AUDIO_BYTES", 100)
    r = client.post(f"/lernen/{card['id']}/sprache", files={"audio": ("a.webm", b"\x00" * 500, "audio/webm")})
    assert r.status_code == 400 and "zu groß" in r.json()["fehler"]

    def unavailable(name, threads):
        raise speech.SpeechUnavailable("Spracherkennung ist nicht installiert (faster-whisper fehlt).")
    monkeypatch.setattr(speech, "_load", unavailable)
    monkeypatch.setattr(speech, "MAX_AUDIO_BYTES", 10 << 20)
    r = client.post(f"/lernen/{card['id']}/sprache", files={"audio": ("a.webm", b"\x00" * 10, "audio/webm")})
    assert r.status_code == 503 and "nicht installiert" in r.json()["fehler"]


def test_prepare_endpoint(client, monkeypatch):
    called = []
    monkeypatch.setattr(speech, "preload", lambda name, threads: called.append((name, threads)))
    assert client.post("/lernen/sprache/vorbereiten").json() == {"ok": True}
    assert called == [(main.settings.whisper_model, main.settings.whisper_threads)]
