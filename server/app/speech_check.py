"""Selbsttest der Spracherkennung auf dem Pi (für den Workflow „Diagnose“ oder von Hand):

    cd ~/vorlesungs-nacharbeitung/server && .venv/bin/python -m app.speech_check

Lädt das eingestellte Whisper-Modell, lässt es 15 Sekunden Testaudio verarbeiten (ohne
Stille-Filter, damit das Modell wirklich rechnet) und gibt Zeiten und Speicherbedarf aus.
"""

import resource
import sys
import time


def main() -> int:
    from .config import settings
    print(f"Modell: {settings.whisper_model} · Threads: {settings.whisper_threads} · Beam: {settings.whisper_beam}")
    try:
        import numpy as np
        from faster_whisper import WhisperModel
    except ImportError as e:
        print(f"FEHLER: faster-whisper nicht installiert ({e})")
        return 1
    start = time.monotonic()
    try:
        model = WhisperModel(settings.whisper_model, device="cpu", compute_type="int8",
                             cpu_threads=settings.whisper_threads)
    except Exception as e:
        print(f"FEHLER beim Laden: {type(e).__name__}: {e}")
        return 1
    print(f"Laden: {time.monotonic() - start:.1f} s")

    rng = np.random.default_rng(0)
    seconds = 15
    t = np.arange(16000 * seconds) / 16000
    audio = (0.05 * np.sin(2 * np.pi * 220 * t) + 0.01 * rng.standard_normal(t.size)).astype(np.float32)
    start = time.monotonic()
    segments, _info = model.transcribe(audio, language="de", beam_size=settings.whisper_beam, vad_filter=False,
                                       condition_on_previous_text=False)
    text = " ".join(s.text for s in segments)
    took = time.monotonic() - start
    print(f"Erkennung von {seconds} s Testaudio: {took:.1f} s (Faktor {took / seconds:.2f} – unter 1 = schneller als Echtzeit)")
    print(f"Erkannter Text (bei Testaudio egal): {text.strip()[:80]!r}")
    rss_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
    print(f"Speicher (Spitze): {rss_mb:.0f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
