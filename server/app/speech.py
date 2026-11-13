"""Spracherkennung auf dem Pi (Whisper über faster-whisper, läuft auf der CPU, nichts verlässt den Pi).

Die Aufnahme kommt aus dem Browser (WebM/Opus bzw. MP4/AAC vom iPhone) und wird mit PyAV
dekodiert – ffmpeg muss dafür nicht installiert sein. Das Modell wird beim ersten Bedarf geladen
(die Lernseite stößt das schon beim Öffnen an) und bleibt danach im Speicher. Füllwörter und
Versprecher entfernt später Claude beim Besprechen der Antwort.
"""

import logging
import re
import threading
import time

log = logging.getLogger(__name__)

MAX_AUDIO_BYTES = 10 << 20   # ~5 Minuten Opus/AAC
MAX_SECONDS = 240
PROMPT_CHARS = 400

_model = None
_model_name = None
_load_lock = threading.Lock()
_run_lock = threading.Lock()   # eine Erkennung gleichzeitig – mehr schafft der Pi nicht sinnvoll


class SpeechUnavailable(Exception):
    pass


def _load(name: str, threads: int):
    global _model, _model_name
    with _load_lock:
        if _model is not None and _model_name == name:
            return _model
        try:
            from faster_whisper import WhisperModel
        except ImportError as e:
            raise SpeechUnavailable("Spracherkennung ist nicht installiert (faster-whisper fehlt).") from e
        log.info("Lade Whisper-Modell %s (%d Threads) …", name, threads)
        start = time.monotonic()
        _model = WhisperModel(name, device="cpu", compute_type="int8", cpu_threads=threads)
        _model_name = name
        log.info("Whisper-Modell %s geladen in %.1f s", name, time.monotonic() - start)
        return _model


def preload(name: str, threads: int) -> None:
    """Lädt das Modell im Hintergrund, damit die erste Aufnahme nicht extra warten muss."""
    if _model is not None and _model_name == name:
        return

    def run():
        try:
            _load(name, threads)
        except Exception:
            log.exception("Whisper-Modell %s konnte nicht geladen werden", name)
    threading.Thread(target=run, daemon=True).start()


def prompt_for(question: str, topic: str = "") -> str:
    """Hinweistext für Whisper: Thema und Frage der Karte – hilft bei Fachbegriffen.
    Formeln ($…$) und LaTeX-Befehle werden entfernt, sie würden die Erkennung eher stören."""
    text = re.sub(r"\$\$.*?\$\$|\$[^$]*\$", " ", f"{topic}. {question}", flags=re.S)
    text = re.sub(r"\\[a-zA-Z]+|[*_`#>{}]", " ", text)
    return re.sub(r"\s+", " ", text).strip(" .")[:PROMPT_CHARS]


def transcribe(path: str, *, model: str, threads: int, beam_size: int, prompt: str = "") -> str:
    """Erkennt deutsche Sprache in einer Audiodatei. Rückgabe: Text (leer, wenn nichts gesagt wurde)."""
    whisper = _load(model, threads)
    with _run_lock:
        start = time.monotonic()
        segments, info = whisper.transcribe(
            path, language="de", beam_size=beam_size, vad_filter=True,
            condition_on_previous_text=False, initial_prompt=prompt or None)
        if info.duration > MAX_SECONDS:
            raise ValueError(f"Die Aufnahme ist zu lang (höchstens {MAX_SECONDS // 60} Minuten).")
        text = " ".join(s.text.strip() for s in segments)
        log.info("Sprache erkannt: %.1f s Aufnahme (%.1f s mit Sprache) in %.1f s, %d Zeichen",
                 info.duration, getattr(info, "duration_after_vad", info.duration), time.monotonic() - start, len(text))
    return re.sub(r"\s+", " ", text).strip()
