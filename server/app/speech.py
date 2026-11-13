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


SAMPLE_RATE = 16000


def decode(path: str):
    """Audiodatei → 16 kHz Mono (float32-Array), mit PyAV.

    Bewusst selbst statt mit faster_whisper.decode_audio: Das übergibt PyAV einen Parameter
    (metadata_errors), den manche PyAV-Versionen nicht kennen – je nachdem, was pip auf dem Pi
    installiert, schlug das Einlesen sonst fehl.
    """
    import av
    import numpy as np

    resampler = av.audio.resampler.AudioResampler(format="s16", layout="mono", rate=SAMPLE_RATE)
    chunks = []

    def add(result):
        # ältere PyAV-Versionen liefern einen Frame (oder None), neuere eine Liste
        for out in (result if isinstance(result, list) else [result]):
            if out is not None:
                chunks.append(out.to_ndarray())

    container = av.open(path)
    try:
        if not container.streams.audio:
            raise ValueError("Die Aufnahme enthält keine Tonspur.")
        stream = container.streams.audio[0]
        for frame in container.decode(stream):
            frame.pts = None  # Zeitstempel der Browser-Aufnahmen sind nicht immer lückenlos
            add(resampler.resample(frame))
        try:
            add(resampler.resample(None))  # Rest aus dem Resampler holen
        except (TypeError, ValueError):
            pass  # sehr alte PyAV-Versionen kennen das Leeren nicht
    finally:
        container.close()
    if not chunks:
        return np.zeros(0, dtype=np.float32)
    return (np.concatenate(chunks, axis=1).reshape(-1).astype(np.float32) / 32768.0)


def transcribe(path: str, *, model: str, threads: int, beam_size: int, prompt: str = "") -> str:
    """Erkennt deutsche Sprache in einer Audiodatei. Rückgabe: Text (leer, wenn nichts gesagt wurde)."""
    audio = decode(path)
    if audio.size / SAMPLE_RATE > MAX_SECONDS:
        raise ValueError(f"Die Aufnahme ist zu lang (höchstens {MAX_SECONDS // 60} Minuten).")
    if audio.size < SAMPLE_RATE // 4:   # unter 0,25 s: nichts gesagt
        return ""
    whisper = _load(model, threads)
    with _run_lock:
        start = time.monotonic()
        segments, info = whisper.transcribe(
            audio, language="de", beam_size=beam_size, vad_filter=True,
            condition_on_previous_text=False, initial_prompt=prompt or None)
        if info.duration > MAX_SECONDS:
            raise ValueError(f"Die Aufnahme ist zu lang (höchstens {MAX_SECONDS // 60} Minuten).")
        text = " ".join(s.text.strip() for s in segments)
        log.info("Sprache erkannt: %.1f s Aufnahme (%.1f s mit Sprache) in %.1f s, %d Zeichen",
                 info.duration, getattr(info, "duration_after_vad", info.duration), time.monotonic() - start, len(text))
    return re.sub(r"\s+", " ", text).strip()
