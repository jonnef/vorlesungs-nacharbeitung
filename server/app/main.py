"""Web-App (FastAPI): Oberfläche für Module/Notizen und API für den Mac-Watcher."""

import json
import logging
import secrets
import tempfile
import threading
from contextlib import asynccontextmanager
from pathlib import Path

import anthropic
import markdown as md
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from .config import settings
from .db import Database
from .prompt import PAGE_RE, TS_RE
from .service import BudgetError, Service, api_error_text
from .transcript import fmt_ts

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("vorlesung")

service = Service(settings, Database(settings.db_path))
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
templates.env.globals["fmt_ts"] = fmt_ts


def _worker(stop: threading.Event) -> None:
    while not stop.wait(settings.poll_interval_sec):
        try:
            service.poll_jobs()
        except Exception:
            log.exception("Fehler im Hintergrund-Worker")


@asynccontextmanager
async def lifespan(app: FastAPI):
    stop = threading.Event()
    thread = threading.Thread(target=_worker, args=(stop,), daemon=True)
    thread.start()
    yield
    stop.set()


app = FastAPI(title="Vorlesungs-Nacharbeitung", lifespan=lifespan)

# ---------- Zugriffsschutz ----------

basic = HTTPBasic(auto_error=False)


def web_auth(creds: HTTPBasicCredentials | None = Depends(basic)) -> None:
    if not settings.web_password:
        return
    if creds is None or not secrets.compare_digest(creds.password, settings.web_password):
        raise HTTPException(401, "Anmeldung erforderlich", headers={"WWW-Authenticate": "Basic"})


def api_auth(request: Request) -> None:
    if not settings.api_token:
        raise HTTPException(503, "API_TOKEN ist auf dem Server nicht gesetzt.")
    auth = request.headers.get("authorization", "")
    if not secrets.compare_digest(auth, f"Bearer {settings.api_token}"):
        raise HTTPException(401, "Ungültiges API-Token")


# ---------- Hilfen ----------

def _get(sql: str, *args) -> dict:
    with service.db.connect() as conn:
        row = conn.execute(sql, args).fetchone()
    if not row:
        raise HTTPException(404, "Nicht gefunden")
    return dict(row)


def _all(sql: str, *args) -> list[dict]:
    with service.db.connect() as conn:
        return [dict(r) for r in conn.execute(sql, args).fetchall()]


def _save_upload(upload: UploadFile) -> Path:
    suffix = Path(upload.filename or "").suffix.lower()
    if suffix != ".pdf":
        raise HTTPException(400, f"Nur PDF-Dateien werden unterstützt ({upload.filename}).")
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    with tmp:
        while chunk := upload.file.read(1 << 20):
            tmp.write(chunk)
    return Path(tmp.name)


def _add_script(module_id: int, upload: UploadFile) -> tuple[int, bool]:
    tmp = _save_upload(upload)
    try:
        return service.add_script(module_id, upload.filename, tmp)
    finally:
        tmp.unlink(missing_ok=True)


def _create_job(lecture_id: int) -> int:
    try:
        return service.create_job(lecture_id)
    except anthropic.APIError as e:
        log.error("Token-Zählung für Vorlesung %s fehlgeschlagen: %s", lecture_id, api_error_text(e))
        raise HTTPException(502, f"Claude-API-Fehler bei der Token-Zählung: {api_error_text(e)}") from e


def render_notes(notes: str) -> str:
    """Markdown → HTML; Zeitstempel und Seitenangaben werden hervorgehoben."""
    html = md.markdown(notes, extensions=["extra", "sane_lists"])
    html = TS_RE.sub(r'<span class="ts">[\1]</span>', html)
    return PAGE_RE.sub(r'<span class="page">[\1 S. \2]</span>', html)


def _budget() -> dict:
    return {
        "budget": settings.monthly_budget_usd,
        "spent": service.month_spent_usd(),
        "reserved": service.reserved_usd(),
        "left": service.budget_left_usd(),
        "model": settings.model,
    }


# ---------- API für den Mac ----------

class LectureIn(BaseModel):
    title: str
    source_filename: str
    duration_sec: float
    segments: list[dict]


@app.post("/api/modules/{module_name}/scripts", dependencies=[Depends(api_auth)])
def api_upload_script(module_name: str, file: UploadFile = File(...)):
    module_id = service.get_or_create_module(module_name)
    script_id, created = _add_script(module_id, file)
    return {"script_id": script_id, "created": created}


@app.post("/api/modules/{module_name}/lectures", dependencies=[Depends(api_auth)])
def api_add_lecture(module_name: str, body: LectureIn):
    module_id = service.get_or_create_module(module_name)
    lecture_id = service.add_lecture(
        module_id, body.title, body.source_filename, body.duration_sec, body.segments
    )
    job_id = _create_job(lecture_id)
    return {"lecture_id": lecture_id, "job_id": job_id}


@app.get("/api/lectures/{lecture_id}", dependencies=[Depends(api_auth)])
def api_lecture(lecture_id: int):
    lec = _get("SELECT l.id, l.title, m.name AS module FROM lectures l"
               " JOIN modules m ON m.id = l.module_id WHERE l.id = ?", lecture_id)
    job = service.latest_job(lecture_id) or {}
    return {
        **lec,
        "status": job.get("status", "none"),
        "notes_md": job.get("notes_md"),
        "warnings": json.loads(job.get("warnings_json") or "[]"),
        "error": job.get("error"),
    }


# ---------- Weboberfläche ----------

@app.get("/", response_class=HTMLResponse, dependencies=[Depends(web_auth)])
def index(request: Request):
    modules = _all(
        "SELECT m.*, (SELECT COUNT(*) FROM lectures l WHERE l.module_id = m.id) AS lectures,"
        " (SELECT COUNT(*) FROM scripts s WHERE s.module_id = m.id) AS scripts"
        " FROM modules m ORDER BY m.name"
    )
    return templates.TemplateResponse(request, "index.html", {"modules": modules, "b": _budget()})


@app.post("/modules", dependencies=[Depends(web_auth)])
def create_module(name: str = Form(...)):
    try:
        module_id = service.get_or_create_module(name)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return RedirectResponse(f"/modules/{module_id}", status_code=303)


@app.get("/modules/{module_id}", response_class=HTMLResponse, dependencies=[Depends(web_auth)])
def module_page(request: Request, module_id: int):
    module = _get("SELECT * FROM modules WHERE id = ?", module_id)
    scripts = _all("SELECT * FROM scripts WHERE module_id = ? ORDER BY id", module_id)
    lectures = _all("SELECT id, title, source_filename, duration_sec, created_at FROM lectures"
                    " WHERE module_id = ? ORDER BY source_filename", module_id)
    for lec in lectures:
        lec["job"] = service.latest_job(lec["id"])
    return templates.TemplateResponse(request, "module.html", {
        "module": module, "scripts": scripts, "lectures": lectures, "b": _budget()})


@app.post("/modules/{module_id}/scripts", dependencies=[Depends(web_auth)])
def upload_scripts(module_id: int, files: list[UploadFile] = File(...)):
    _get("SELECT id FROM modules WHERE id = ?", module_id)
    for f in files:
        _add_script(module_id, f)
    return RedirectResponse(f"/modules/{module_id}", status_code=303)


@app.get("/lectures/{lecture_id}", response_class=HTMLResponse, dependencies=[Depends(web_auth)])
def lecture_page(request: Request, lecture_id: int):
    lec = _get("SELECT l.*, m.name AS module FROM lectures l JOIN modules m ON m.id = l.module_id"
               " WHERE l.id = ?", lecture_id)
    job = service.latest_job(lecture_id)
    notes_html = render_notes(job["notes_md"]) if job and job.get("notes_md") else None
    warnings = json.loads(job["warnings_json"]) if job and job.get("warnings_json") else []
    segments = json.loads(lec.pop("segments_json"))
    return templates.TemplateResponse(request, "lecture.html", {
        "lec": lec, "job": job, "notes_html": notes_html, "warnings": warnings,
        "segments": segments, "b": _budget()})


@app.get("/lectures/{lecture_id}/notizen.md", response_class=PlainTextResponse,
         dependencies=[Depends(web_auth)])
def lecture_notes_md(lecture_id: int):
    job = service.latest_job(lecture_id)
    if not job or not job.get("notes_md"):
        raise HTTPException(404, "Noch keine Notizen")
    return job["notes_md"]


@app.post("/lectures/{lecture_id}/jobs", dependencies=[Depends(web_auth)])
def new_job(lecture_id: int):
    _get("SELECT id FROM lectures WHERE id = ?", lecture_id)
    _create_job(lecture_id)
    return RedirectResponse(f"/lectures/{lecture_id}", status_code=303)


@app.post("/jobs/{job_id}/submit", dependencies=[Depends(web_auth)])
def submit_job(job_id: int):
    job = _get("SELECT * FROM jobs WHERE id = ?", job_id)
    try:
        service.submit_job(job_id)
    except BudgetError:
        pass  # Grund steht im Job und wird angezeigt
    except anthropic.APIError as e:
        service._set(job_id, error=f"Abschicken fehlgeschlagen: {api_error_text(e)}")
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return RedirectResponse(f"/lectures/{job['lecture_id']}", status_code=303)


@app.post("/poll", dependencies=[Depends(web_auth)])
def poll_now(back: str = Form("/")):
    service.poll_jobs()
    safe = back.startswith("/") and not back.startswith("//")
    return RedirectResponse(back if safe else "/", status_code=303)


@app.get("/kosten", response_class=HTMLResponse, dependencies=[Depends(web_auth)])
def usage_page(request: Request):
    rows = _all(
        "SELECT u.*, l.title, l.id AS lecture_id FROM usage_log u"
        " LEFT JOIN jobs j ON j.id = u.job_id LEFT JOIN lectures l ON l.id = j.lecture_id"
        " ORDER BY u.id DESC LIMIT 200"
    )
    return templates.TemplateResponse(request, "usage.html", {"rows": rows, "b": _budget()})
