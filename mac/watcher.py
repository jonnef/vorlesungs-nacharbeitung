#!/usr/bin/env python3
"""Mac-Watcher: beobachtet den iCloud-Ordner, transkribiert Videos lokal und holt die Notizen.

Ordnerstruktur (iCloud Drive/Dokumente/Studium):

    Vorlesungen/
      <Modul>/          ← heruntergeladene Vorlesungsvideos
    <Modul>/            ← dein vorhandener Modulordner
      Skripte/          ← PDFs des Dozenten (werden auf den Pi hochgeladen)
      Transkripte/      ← legt der Watcher an (JSON mit Zeitstempeln)
      Notizen/          ← legt der Watcher an (fertige Markdown-Notizen)
      Glossar.md        ← legt der Watcher an (wächst mit jeder Vorlesung)

Konfiguration über Umgebungsvariablen (setzt install.sh im LaunchAgent):
    VORLESUNG_SERVER   z. B. http://raspberrypi.local:8000
    VORLESUNG_TOKEN    derselbe Wert wie API_TOKEN auf dem Pi
    VORLESUNG_STUDIUM  optional, Standard: iCloud Drive/Dokumente/Studium
    VORLESUNG_SKRIPTE  optional, Unterordner für Dozenten-PDFs, Standard: Skripte
    WHISPER_MODEL      optional, Standard: mlx-community/whisper-large-v3-turbo
"""

import argparse
import hashlib
import json
import logging
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

ICLOUD = Path.home() / "Library/Mobile Documents/com~apple~CloudDocs"
# „Dokumente“ heißt auf der Festplatte „Documents“.
STUDIUM = Path(os.environ.get("VORLESUNG_STUDIUM", ICLOUD / "Documents/Studium")).expanduser()
ROOT = STUDIUM / "Vorlesungen"
SKRIPTE = os.environ.get("VORLESUNG_SKRIPTE", "Skripte")
SERVER = os.environ.get("VORLESUNG_SERVER", "http://raspberrypi.local:8000").rstrip("/")
TOKEN = os.environ.get("VORLESUNG_TOKEN", "")
WHISPER_MODEL = os.environ.get("WHISPER_MODEL", "mlx-community/whisper-large-v3-turbo")
STATE_FILE = Path.home() / ".vorlesung-watcher/state.json"

VIDEO_EXT = {".mp4", ".mov", ".m4v", ".mkv", ".webm", ".avi", ".mp3", ".m4a", ".wav", ".aac"}
STABLE_SEC = 60  # so lange muss eine Datei unverändert sein, bevor sie verarbeitet wird

log = logging.getLogger("watcher")


# ---------- Zustand ----------

def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"scripts": {}, "lectures": {}}


def save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2, ensure_ascii=False))
    tmp.replace(STATE_FILE)


# ---------- HTTP ----------

def api(method: str, path: str, body: bytes | None = None, content_type: str | None = None) -> dict:
    req = urllib.request.Request(SERVER + path, data=body, method=method)
    req.add_header("Authorization", f"Bearer {TOKEN}")
    if content_type:
        req.add_header("Content-Type", content_type)
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read())


def quote(s: str) -> str:
    return urllib.parse.quote(s, safe="")


def upload_pdf(module: str, path: Path) -> dict:
    boundary = uuid.uuid4().hex
    body = (
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; "
        f"filename=\"{path.name}\"\r\nContent-Type: application/pdf\r\n\r\n"
    ).encode() + path.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
    return api("POST", f"/api/modules/{quote(module)}/scripts", body,
               f"multipart/form-data; boundary={boundary}")


# ---------- iCloud ----------

def is_placeholder(p: Path) -> bool:
    return p.name.startswith(".") and p.name.endswith(".icloud")


def request_download(placeholder: Path) -> None:
    """iCloud lagert Dateien evtl. aus („.name.icloud“) – Download anstoßen."""
    real = placeholder.with_name(placeholder.name[1:-len(".icloud")])
    subprocess.run(["brctl", "download", str(real)], capture_output=True)


def is_stable(p: Path) -> bool:
    return time.time() - p.stat().st_mtime > STABLE_SEC


# ---------- Transkription ----------

def media_duration(path: Path) -> float | None:
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        return float(out)
    except (subprocess.CalledProcessError, FileNotFoundError, ValueError):
        return None


def transcribe(path: Path, module: str) -> dict:
    import mlx_whisper  # erst hier importieren, damit --help ohne MLX funktioniert

    log.info("Transkribiere %s …", path.name)
    t0 = time.time()
    result = mlx_whisper.transcribe(
        str(path),
        path_or_hf_repo=WHISPER_MODEL,
        language="de",
        # Verhindert, dass sich Fehler/Wiederholungen durch lange Vorlesungen ziehen.
        condition_on_previous_text=False,
        initial_prompt=f"Vorlesung im Modul {module}.",
    )
    segments = [
        {"start": round(s["start"], 2), "end": round(s["end"], 2), "text": s["text"].strip()}
        for s in result["segments"]
    ]
    duration = media_duration(path) or (segments[-1]["end"] if segments else 0.0)
    log.info("Fertig in %.0f s (%d Segmente, Video %.0f min)", time.time() - t0, len(segments), duration / 60)
    return {"source_filename": path.name, "duration_sec": duration, "segments": segments}


def title_from_filename(name: str) -> str:
    return Path(name).stem.replace("_", " ").strip()


# ---------- Notizen ----------

def write_notes(module_dir: Path, video: Path, info: dict) -> None:
    notes_dir = module_dir / "Notizen"
    notes_dir.mkdir(exist_ok=True)
    header = [f"> Quelle: `{video.name}` · Notizen automatisch erstellt – bitte mit Skript und Video prüfen."]
    for w in info.get("warnings") or []:
        header.append(f"> ⚠️ {w}")
    (notes_dir / f"{video.stem}.md").write_text("\n".join(header) + "\n\n" + info["notes_md"] + "\n")
    log.info("Notizen gespeichert: %s/Notizen/%s.md", module_dir.name, video.stem)


def sync_glossary(module: str, module_dir: Path) -> None:
    """Legt Studium/<Modul>/Glossar.md an bzw. aktualisiert sie, wenn sich Einträge geändert haben."""
    info = api("GET", f"/api/modules/{quote(module)}/glossary")
    if not info.get("count"):
        return
    target = module_dir / "Glossar.md"

    def content(text: str) -> str:  # Datumszeile ignorieren, sonst würde täglich neu geschrieben
        return "\n".join(line for line in text.splitlines() if not line.startswith("_Stand "))

    if target.exists() and content(target.read_text()) == content(info["markdown"]):
        return
    target.write_text(info["markdown"])
    log.info("Glossar aktualisiert: %s/Glossar.md (%d Einträge)", module, info["count"])


# ---------- Hauptschleife ----------

def process_module(video_dir: Path, state: dict, allow_transcribe: bool) -> bool:
    """Verarbeitet Vorlesungen/<Modul>/ und den zugehörigen Modulordner Studium/<Modul>/.

    Gibt True zurück, wenn in diesem Durchlauf transkribiert wurde (teuer → eins pro Runde).
    """
    module = video_dir.name
    module_dir = STUDIUM / module
    (module_dir / SKRIPTE).mkdir(parents=True, exist_ok=True)

    for pdf in sorted((module_dir / SKRIPTE).rglob("*")):
        if is_placeholder(pdf):
            request_download(pdf)
            continue
        if pdf.suffix.lower() != ".pdf" or not is_stable(pdf):
            continue
        digest = hashlib.sha256(pdf.read_bytes()).hexdigest()
        if state["scripts"].get(f"{module}/{pdf.name}") == digest:
            continue
        res = upload_pdf(module, pdf)
        log.info("Skript %s: %s", pdf.name, "hochgeladen" if res["created"] else "war schon vorhanden")
        state["scripts"][f"{module}/{pdf.name}"] = digest
        save_state(state)

    transcribed = False
    for video in sorted(video_dir.glob("*")):
        if is_placeholder(video):
            request_download(video)
            continue
        if video.suffix.lower() not in VIDEO_EXT:
            continue
        key = f"{module}/{video.name}"
        entry = state["lectures"].get(key, {})
        if (module_dir / "Notizen" / f"{video.stem}.md").exists() and entry.get("status") == "done":
            continue

        if "lecture_id" in entry:
            info = api("GET", f"/api/lectures/{entry['lecture_id']}")
            if info["status"] != entry.get("status"):
                log.info("%s: Status %s", video.name, info["status"])
                if info.get("error"):
                    log.warning("%s: %s", video.name, info["error"])
            entry["status"] = info["status"]
            if info["status"] == "done" and info.get("notes_md"):
                write_notes(module_dir, video, info)
            state["lectures"][key] = entry
            save_state(state)
            continue

        if transcribed or not allow_transcribe or not is_stable(video):
            continue
        cache = module_dir / "Transkripte" / f"{video.stem}.json"
        if cache.exists():
            data = json.loads(cache.read_text())
        else:
            data = transcribe(video, module)
            cache.parent.mkdir(exist_ok=True)
            cache.write_text(json.dumps(data, ensure_ascii=False))
            transcribed = True
        body = json.dumps({"title": title_from_filename(video.name), **data}).encode()
        res = api("POST", f"/api/modules/{quote(module)}/lectures", body, "application/json")
        state["lectures"][key] = {"lecture_id": res["lecture_id"], "status": "sent"}
        save_state(state)
        log.info("%s an den Pi geschickt (Vorlesung #%s)", video.name, res["lecture_id"])
    sync_glossary(module, module_dir)
    return transcribed


def run_once(state: dict) -> None:
    try:
        ROOT.mkdir(parents=True, exist_ok=True)
        video_dirs = sorted(p for p in ROOT.iterdir() if p.is_dir() and not p.name.startswith("."))
    except PermissionError as e:
        log.error("Kein Zugriff auf %s – Festplattenvollzugriff für Python erteilen (%s).", STUDIUM, e)
        return
    transcribed = False
    for video_dir in video_dirs:
        try:
            transcribed |= process_module(video_dir, state, allow_transcribe=not transcribed)
        except urllib.error.HTTPError as e:
            log.error("%s: Server antwortet %s: %s", video_dir.name, e.code, e.read().decode(errors="replace"))
        except urllib.error.URLError as e:
            log.warning("Pi nicht erreichbar (%s) – nächster Versuch später.", e.reason)
            return
        except PermissionError as e:
            log.error("Kein Zugriff auf %s – Festplattenvollzugriff für Python erteilen (%s).", STUDIUM, e)
            return


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--once", action="store_true", help="nur einen Durchlauf, dann beenden")
    parser.add_argument("--interval", type=int, default=60, help="Sekunden zwischen Durchläufen")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if not TOKEN:
        sys.exit("VORLESUNG_TOKEN ist nicht gesetzt.")
    log.info("Beobachte %s, Server %s", STUDIUM, SERVER)
    state = load_state()
    while True:
        run_once(state)
        if args.once:
            break
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
