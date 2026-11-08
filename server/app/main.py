"""Web-App (FastAPI): Oberfläche für Module/Notizen und API für den Mac-Watcher."""

import json
import logging
import re
import secrets
import tempfile
import threading
from contextlib import asynccontextmanager
from datetime import date, datetime
from pathlib import Path
from urllib.parse import quote, urlencode

import anthropic
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from . import cards, conceptmap, demo, exam, glossary, hints, ordering, search, slides
from .config import settings
from .db import Database
from .render import render_inline, render_notes
from .service import BudgetError, Service, api_error_text
from .transcript import fmt_ts

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("vorlesung")

service = Service(settings, Database(settings.db_path))
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
templates.env.globals["fmt_ts"] = fmt_ts
templates.env.globals["initial"] = glossary.initial
templates.env.globals["hint_kinds"] = hints.KINDS
templates.env.globals["demo"] = settings.demo_mode
templates.env.globals["demo_login_url"] = settings.demo_login_url


def _worker(stop: threading.Event) -> None:
    while not stop.wait(settings.poll_interval_sec):
        # Jeder Schritt einzeln, damit ein Fehler (z. B. beim Glossar) die übrigen nicht blockiert.
        for step in (service.poll_jobs, service.ensure_glossary_jobs, service.ensure_conceptmap_jobs,
                     service.ensure_hint_jobs,
                     service.ensure_card_jobs, service.ensure_cardcheck_jobs, service.ensure_exam_jobs):
            try:
                step()
            except Exception:
                log.exception("Fehler im Hintergrund-Worker (%s)", step.__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.demo_mode:
        # Vorschau: Beispieldaten anlegen, kein Hintergrund-Worker (keine Claude-Aufträge).
        demo.seed_if_empty(service.db)
        yield
        return
    stop = threading.Event()
    thread = threading.Thread(target=_worker, args=(stop,), daemon=True)
    thread.start()
    yield
    stop.set()


app = FastAPI(title="Vorlesungs-Nacharbeitung", lifespan=lifespan)

# Hinter Caddy läuft die App unter einem Unterpfad (z. B. /vorlesungen). Caddy entfernt ihn und
# meldet ihn per X-Forwarded-Prefix; Links und Weiterleitungen setzen ihn wieder davor. Direkt
# über Port 8000 aufgerufen fehlt der Header und alles bleibt wie bisher.
PREFIX_RE = re.compile(r"^(/[A-Za-z0-9_-]+)*$")


@app.middleware("http")
async def forwarded_prefix(request: Request, call_next):
    prefix = request.headers.get("x-forwarded-prefix", "").rstrip("/")
    request.state.base = prefix if PREFIX_RE.match(prefix) else ""
    return await call_next(request)


@app.middleware("http")
async def read_only_preview(request: Request, call_next):
    """In der Vorschau ist nur Lesen erlaubt; die API für den Mac-Watcher gibt es dort nicht."""
    if settings.demo_mode:
        if request.url.path.startswith("/api/"):
            return JSONResponse({"detail": "In der Vorschau nicht verfügbar."}, status_code=404)
        if request.method not in ("GET", "HEAD"):
            return PlainTextResponse("In der Vorschau mit Beispieldaten ist das nicht möglich.", status_code=403)
    return await call_next(request)


def _redirect(request: Request, path: str) -> RedirectResponse:
    return RedirectResponse(request.state.base + path, status_code=303)

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


def _add_lecture_slides(module_id: int, upload: UploadFile, lecture_id: int | None = None) -> dict:
    tmp = _save_upload(upload)
    try:
        return service.add_lecture_slides(module_id, upload.filename or "Folien.pdf", tmp, lecture_id)
    finally:
        tmp.unlink(missing_ok=True)


def _create_job(lecture_id: int) -> int:
    try:
        return service.create_job(lecture_id)
    except anthropic.APIError as e:
        log.error("Token-Zählung für Vorlesung %s fehlgeschlagen: %s", lecture_id, api_error_text(e))
        raise HTTPException(502, f"Claude-API-Fehler bei der Token-Zählung: {api_error_text(e)}") from e


templates.env.filters["inline_md"] = render_inline
templates.env.filters["fromjson"] = lambda s: json.loads(s or "[]")


def _glossary_markdown(module: dict) -> str:
    groups = service.module_glossary(module["id"])
    return glossary.to_markdown(module["name"], groups, datetime.now().strftime("%d.%m.%Y"))


def _exam_markdown(module: dict, data: dict) -> str:
    """Klausurvorbereitung als Datei: Legende der Vorlesungskürzel + Inhalt."""
    return exam.legend(data["lectures"]) + "\n\n" + data["markdown"].strip() + "\n"


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


@app.post("/api/modules/{module_name}/lecture-slides", dependencies=[Depends(api_auth)])
def api_upload_lecture_slides(module_name: str, file: UploadFile = File(...)):
    """Bemalte Folien aus einer Vorlesung; die Vorlesung ergibt sich aus dem Dateinamen."""
    module_id = service.get_or_create_module(module_name)
    res = _add_lecture_slides(module_id, file)
    title = None
    if res["lecture_id"]:
        title = _get("SELECT title FROM lectures WHERE id = ?", res["lecture_id"])["title"]
    return {**res, "lecture_title": title}


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
    notes = service.latest_notes(lecture_id) or {}
    return {
        **lec,
        "status": job.get("status", "none"),
        # Neueste fertige Fassung – auch während eine neue entsteht.
        "notes_md": notes.get("notes_md"),
        "notes_job_id": notes.get("id"),
        "warnings": json.loads(notes.get("warnings_json") or "[]"),
        "error": job.get("error"),
    }


@app.get("/api/modules/{module_name}/notes-versions", dependencies=[Depends(api_auth)])
def api_notes_versions(module_name: str):
    """Je Vorlesung die ID der neuesten fertigen Notizen – der Mac erkennt daran neue Fassungen."""
    rows = _all(
        "SELECT l.id, (SELECT MAX(j.id) FROM jobs j WHERE j.lecture_id = l.id AND j.kind = 'notes'"
        " AND j.status = 'done' AND j.notes_md IS NOT NULL) AS notes_job_id"
        " FROM lectures l JOIN modules m ON m.id = l.module_id WHERE m.name = ?", module_name)
    return {str(r["id"]): r["notes_job_id"] for r in rows}


@app.get("/api/modules/{module_name}/glossary", dependencies=[Depends(api_auth)])
def api_glossary(module_name: str):
    with service.db.connect() as conn:
        row = conn.execute("SELECT * FROM modules WHERE name = ?", (module_name,)).fetchone()
    if not row:
        return {"count": 0, "markdown": ""}
    groups = service.module_glossary(row["id"])
    if not groups:
        return {"count": 0, "markdown": ""}
    return {"count": len(groups), "markdown": _glossary_markdown(dict(row))}


@app.get("/api/modules/{module_name}/hints", dependencies=[Depends(api_auth)])
def api_hints(module_name: str):
    with service.db.connect() as conn:
        row = conn.execute("SELECT * FROM modules WHERE name = ?", (module_name,)).fetchone()
    if not row or not service.hints_status(row["id"])["lectures"]:
        return {"count": 0, "markdown": ""}
    items = service.module_hints(row["id"])
    return {"count": len(items), "markdown": hints.to_markdown(row["name"], items, datetime.now().strftime("%d.%m.%Y"))}


@app.get("/api/modules/{module_name}/exam", dependencies=[Depends(api_auth)])
def api_exam(module_name: str):
    with service.db.connect() as conn:
        row = conn.execute("SELECT * FROM modules WHERE name = ?", (module_name,)).fetchone()
    data = service.module_exam(row["id"]) if row else None
    if not data or not data["markdown"]:
        return {"markdown": "", "updated_at": None}
    return {"markdown": _exam_markdown(dict(row), data), "updated_at": data["updated_at"]}


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
def create_module(request: Request, name: str = Form(...)):
    try:
        module_id = service.get_or_create_module(name)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return _redirect(request, f"/modules/{module_id}")


@app.get("/modules/{module_id}", response_class=HTMLResponse, dependencies=[Depends(web_auth)])
def module_page(request: Request, module_id: int):
    module = _get("SELECT * FROM modules WHERE id = ?", module_id)
    scripts = _all("SELECT * FROM scripts WHERE module_id = ? ORDER BY id", module_id)
    lectures = _all("SELECT id, title, source_filename, duration_sec, created_at FROM lectures"
                    " WHERE module_id = ? ORDER BY source_filename", module_id)
    sort_basis = ordering.annotate(lectures)
    lectures.sort(key=lambda l: l["sort_key"], reverse=True)  # neueste zuerst; im Browser umstellbar
    for lec in lectures:
        lec["job"] = service.latest_job(lec["id"])
    return templates.TemplateResponse(request, "module.html", {
        "module": module, "scripts": scripts, "lectures": lectures, "sort_basis": sort_basis, "b": _budget(),
        "glossary_count": len(service.module_glossary(module_id)),
        "glossary_status": service.glossary_status(module_id),
        "exam": service.module_exam(module_id),
        "open_slides": service.lecture_slides_of(module_id=module_id),
        "hint_count": len(service.module_hints(module_id)),
        "hints_status": service.hints_status(module_id),
        "cards_status": service.cards_status(module_id),
        "conceptmap": service.module_conceptmap(module_id)})


@app.get("/modules/{module_id}/suche", response_class=HTMLResponse, dependencies=[Depends(web_auth)])
def search_page(request: Request, module_id: int, q: str = "", transkript: bool = False):
    module = _get("SELECT * FROM modules WHERE id = ?", module_id)
    needles = search.terms(q)
    results, total = [], 0
    if needles:
        lectures = _all("SELECT id, title, segments_json FROM lectures WHERE module_id = ? ORDER BY source_filename",
                        module_id)
        for lec in lectures:
            notes = service.latest_notes(lec["id"])
            note_hits = search.search_notes(notes["notes_md"], needles) if notes else []
            transcript_hits = (search.search_transcript(json.loads(lec["segments_json"]), needles)
                               if transkript else [])
            if note_hits or transcript_hits:
                results.append({"id": lec["id"], "title": lec["title"], "notes": note_hits,
                                "transcript": transcript_hits})
                total += len(note_hits) + len(transcript_hits)
    return templates.TemplateResponse(request, "search.html", {
        "module": module, "q": q, "transkript": transkript, "results": results, "total": total,
        "searched": bool(needles), "b": _budget()})


@app.get("/modules/{module_id}/neu-erstellen", response_class=HTMLResponse, dependencies=[Depends(web_auth)])
def regenerate_confirm(request: Request, module_id: int):
    module = _get("SELECT * FROM modules WHERE id = ?", module_id)
    return templates.TemplateResponse(request, "regenerate.html", {
        "module": module, "plan": service.regeneration_plan(module_id), "b": _budget()})


@app.post("/modules/{module_id}/neu-erstellen", dependencies=[Depends(web_auth)])
def regenerate_module(request: Request, module_id: int):
    _get("SELECT id FROM modules WHERE id = ?", module_id)
    try:
        service.regenerate_module(module_id)
    except anthropic.APIError as e:
        log.error("Neu erstellen für Modul %s abgebrochen: %s", module_id, api_error_text(e))
        raise HTTPException(502, f"Claude-API-Fehler bei der Token-Zählung: {api_error_text(e)}") from e
    return _redirect(request, f"/modules/{module_id}")


@app.get("/modules/{module_id}/pruefungshinweise", response_class=HTMLResponse, dependencies=[Depends(web_auth)])
def hints_page(request: Request, module_id: int):
    module = _get("SELECT * FROM modules WHERE id = ?", module_id)
    items = service.module_hints(module_id)
    lectures: list[dict] = []
    for h in items:
        if not lectures or lectures[-1]["id"] != h["lecture_id"]:
            lectures.append({"id": h["lecture_id"], "title": h["lecture_title"], "hints": []})
        lectures[-1]["hints"].append(h)
    counts = {k: sum(1 for h in items if h["kind"] == k) for k in hints.KINDS}
    return templates.TemplateResponse(request, "hints.html", {
        "module": module, "lectures": lectures, "counts": counts, "total": len(items),
        "status": service.hints_status(module_id), "b": _budget()})


@app.get("/modules/{module_id}/pruefungshinweise.md", response_class=PlainTextResponse,
         dependencies=[Depends(web_auth)])
def hints_md(module_id: int):
    module = _get("SELECT * FROM modules WHERE id = ?", module_id)
    text = hints.to_markdown(module["name"], service.module_hints(module_id), datetime.now().strftime("%d.%m.%Y"))
    filename = quote(f"Prüfungshinweise {module['name']}.md")
    return PlainTextResponse(text, media_type="text/markdown; charset=utf-8",
                             headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"})


@app.get("/modules/{module_id}/klausur", response_class=HTMLResponse, dependencies=[Depends(web_auth)])
def exam_page(request: Request, module_id: int):
    module = _get("SELECT * FROM modules WHERE id = ?", module_id)
    data = service.module_exam(module_id)
    html = None
    if data["markdown"]:
        html = exam.link_citations(render_notes(data["markdown"]), [l["id"] for l in data["lectures"]],
                                   request.state.base)
    return templates.TemplateResponse(request, "exam.html", {
        "module": module, "data": data, "html": html,
        "lecture_count": len(service.exam_lectures(module_id)), "b": _budget()})


@app.get("/modules/{module_id}/klausur.md", response_class=PlainTextResponse, dependencies=[Depends(web_auth)])
def exam_md(module_id: int):
    module = _get("SELECT * FROM modules WHERE id = ?", module_id)
    data = service.module_exam(module_id)
    if not data["markdown"]:
        raise HTTPException(404, "Noch keine Klausurvorbereitung")
    filename = quote(f"Klausurvorbereitung {module['name']}.md")
    return PlainTextResponse(_exam_markdown(module, data), media_type="text/markdown; charset=utf-8",
                             headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"})


@app.post("/modules/{module_id}/klausur", dependencies=[Depends(web_auth)])
def exam_regenerate(request: Request, module_id: int):
    _get("SELECT id FROM modules WHERE id = ?", module_id)
    try:
        service.create_exam_job(module_id)
    except anthropic.APIError as e:
        raise HTTPException(502, f"Claude-API-Fehler bei der Token-Zählung: {api_error_text(e)}") from e
    return _redirect(request, f"/modules/{module_id}/klausur")


@app.get("/modules/{module_id}/glossar", response_class=HTMLResponse, dependencies=[Depends(web_auth)])
def glossary_page(request: Request, module_id: int):
    module = _get("SELECT * FROM modules WHERE id = ?", module_id)
    return templates.TemplateResponse(request, "glossary.html", {
        "module": module, "groups": service.module_glossary(module_id),
        "status": service.glossary_status(module_id), "b": _budget()})


@app.get("/modules/{module_id}/glossar.md", response_class=PlainTextResponse, dependencies=[Depends(web_auth)])
def glossary_md(module_id: int):
    module = _get("SELECT * FROM modules WHERE id = ?", module_id)
    filename = quote(f"Glossar {module['name']}.md")
    return PlainTextResponse(_glossary_markdown(module), media_type="text/markdown; charset=utf-8",
                             headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"})


@app.get("/modules/{module_id}/concept-map", response_class=HTMLResponse, dependencies=[Depends(web_auth)])
def conceptmap_page(request: Request, module_id: int):
    module = _get("SELECT * FROM modules WHERE id = ?", module_id)
    data = service.module_conceptmap(module_id)
    if data["map"]:
        for n in data["map"]["nodes"]:
            n["definition_html"] = render_inline(n["definition"])
    return templates.TemplateResponse(request, "conceptmap.html", {
        "module": module, "data": data, "kinds": conceptmap.KINDS,
        "glossary_status": service.glossary_status(module_id), "b": _budget()})


@app.post("/modules/{module_id}/concept-map", dependencies=[Depends(web_auth)])
def conceptmap_regenerate(request: Request, module_id: int):
    _get("SELECT id FROM modules WHERE id = ?", module_id)
    try:
        service.create_conceptmap_job(module_id)
    except anthropic.APIError as e:
        raise HTTPException(502, f"Claude-API-Fehler bei der Token-Zählung: {api_error_text(e)}") from e
    return _redirect(request, f"/modules/{module_id}/concept-map")


# ---------- Lernen ----------

def _learn_filters(modul: str, art: str, ohne_tr: str) -> dict:
    """Auswahl beim Lernen: Modul (leer = alle), Art (leer = beides), nur ohne Taschenrechner."""
    return {"modul": int(modul) if modul.isdigit() else None,
            "art": art if art in cards.KINDS else "",
            "ohne_tr": ohne_tr in ("1", "on", "true")}


def _learn_query(f: dict) -> str:
    params = {k: v for k, v in (("modul", f["modul"] or ""), ("art", f["art"]), ("ohne_tr", "1" if f["ohne_tr"] else ""))
              if v}
    return ("?" + urlencode(params)) if params else ""


@app.get("/lernen", response_class=HTMLResponse, dependencies=[Depends(web_auth)])
def learn_page(request: Request, modul: str = "", art: str = "", ohne_tr: str = "", nr: int = 0):
    f = _learn_filters(modul, art, ohne_tr)
    today = date.today()
    sel = {"module_id": f["modul"], "kind": f["art"] or None, "no_calculator": f["ohne_tr"]}
    card = service.next_card(today, **sel)
    demo_count = 0
    if settings.demo_mode:
        # Vorschau: Lernstand wird nicht gespeichert, „Nächste Karte“ blättert durch die Beispiele.
        where, args = service._card_where(sel["module_id"], sel["kind"], sel["no_calculator"])
        ids = [r["id"] for r in _all(f"SELECT c.id FROM cards c WHERE {where} ORDER BY c.id", *args)]
        demo_count = len(ids)
        card = service.card(ids[nr % len(ids)]) if ids else None
    view = None
    if card:
        variant_index, variant = cards.variant_for(card)
        front, back = cards.card_markdown(card, variant)
        view = {"front": render_notes(front), "back": render_notes(back), "variant": variant_index + 1,
                "variants": len(card["variants"]),
                "grades": [(g, label, cards.interval_label(cards.schedule(card, g, today)["interval_days"]))
                           for g, label in cards.GRADES.items()]}
    return templates.TemplateResponse(request, "learn.html", {
        "f": f, "query": _learn_query(f), "card": card, "view": view, "nr": nr, "demo_count": demo_count,
        "counts": service.learning_counts(today, **sel), "modules": service.learning_modules(today),
        "all_modules": _all("SELECT id, name FROM modules ORDER BY name"),
        "archived": service.archived_count(f["modul"]), "b": _budget()})


@app.post("/lernen/{card_id}/bewerten", dependencies=[Depends(web_auth)])
def learn_grade(request: Request, card_id: int, grade: int = Form(...), modul: str = Form(""),
                art: str = Form(""), ohne_tr: str = Form("")):
    try:
        service.review_card(card_id, grade, date.today())
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return _redirect(request, "/lernen" + _learn_query(_learn_filters(modul, art, ohne_tr)))


def _safe_back(back: str, fallback: str = "/lernen") -> str:
    return back if back.startswith("/") and not back.startswith("//") else fallback


@app.post("/lernen/{card_id}/archivieren", dependencies=[Depends(web_auth)])
def learn_archive(request: Request, card_id: int, wieder: str = Form(""), back: str = Form("/lernen")):
    _get("SELECT id FROM cards WHERE id = ? AND deleted_at IS NULL", card_id)
    service.set_card_archived(card_id, not wieder)
    return _redirect(request, _safe_back(back))


@app.post("/lernen/{card_id}/loeschen", dependencies=[Depends(web_auth)])
def learn_delete(request: Request, card_id: int, back: str = Form("/lernen")):
    _get("SELECT id FROM cards WHERE id = ? AND deleted_at IS NULL", card_id)
    service.delete_card(card_id)
    return _redirect(request, _safe_back(back))


@app.get("/lernen/karten", response_class=HTMLResponse, dependencies=[Depends(web_auth)])
def cards_page(request: Request, modul: str = "", archiv: str = ""):
    module_id = int(modul) if modul.isdigit() else None
    archived = archiv == "1"
    items = service.list_cards(module_id, archived)
    for c in items:
        c["front_html"] = render_inline(c["variants"][0]["front"])
    params = {k: v for k, v in (("modul", module_id or ""), ("archiv", "1" if archived else "")) if v}
    return templates.TemplateResponse(request, "cards.html", {
        "items": items, "module_id": module_id, "archived": archived,
        "back": "/lernen/karten" + ("?" + urlencode(params) if params else ""),
        "active_count": len(service.list_cards(module_id, False)) if archived else len(items),
        "archived_count": service.archived_count(module_id),
        "all_modules": _all("SELECT id, name FROM modules ORDER BY name"), "today": date.today().isoformat(),
        "check": service.cardcheck_status(module_id), "regen": service.card_regeneration_plan(module_id),
        "cards_running": _all(
            "SELECT COUNT(*) AS c FROM jobs j JOIN lectures l ON l.id = j.lecture_id WHERE j.kind = 'cards'"
            " AND j.status IN ('estimated', 'blocked', 'submitted') AND (? IS NULL OR l.module_id = ?)",
            module_id, module_id)[0]["c"],
        "b": _budget()})


@app.post("/lernen/karten/neu-erstellen", dependencies=[Depends(web_auth)])
def cards_regenerate(request: Request, modul: str = Form(""), back: str = Form("/lernen/karten")):
    """Karten im neuen Stil neu erstellen (Modul oder alle): ungelernte ersetzen, gelernte archivieren."""
    module_id = _get("SELECT id FROM modules WHERE id = ?", int(modul))["id"] if modul.isdigit() else None
    try:
        service.regenerate_cards(module_id)
    except anthropic.APIError as e:
        raise HTTPException(502, f"Claude-API-Fehler bei der Token-Zählung: {api_error_text(e)}") from e
    return _redirect(request, _safe_back(back, "/lernen/karten"))


@app.post("/lernen/karten/pruefen", dependencies=[Depends(web_auth)])
def cards_recheck(request: Request, modul: str = Form(""), back: str = Form("/lernen/karten")):
    """Alle aktiven Karten (eines Moduls oder aller Module) erneut aussortieren lassen."""
    if modul.isdigit():
        module_ids = [_get("SELECT id FROM modules WHERE id = ?", int(modul))["id"]]
    else:
        module_ids = [r["module_id"] for r in _all("SELECT DISTINCT module_id FROM cards WHERE deleted_at IS NULL")]
    try:
        for module_id in module_ids:
            service.create_cardcheck_job(module_id, recheck=True)
    except anthropic.APIError as e:
        raise HTTPException(502, f"Claude-API-Fehler bei der Token-Zählung: {api_error_text(e)}") from e
    return _redirect(request, _safe_back(back, "/lernen/karten"))


@app.post("/modules/{module_id}/scripts", dependencies=[Depends(web_auth)])
def upload_scripts(request: Request, module_id: int, files: list[UploadFile] = File(...)):
    _get("SELECT id FROM modules WHERE id = ?", module_id)
    for f in files:
        _add_script(module_id, f)
    return _redirect(request, f"/modules/{module_id}")


@app.get("/modules/{module_id}/folie/{kuerzel}/{label}.png", dependencies=[Depends(web_auth)])
def slide_image(module_id: int, kuerzel: str, label: str):
    """Seite aus dem Dozenten-PDF als Bild – für die Seitenangaben [Kürzel S. 12] in den Notizen."""
    row = _get(
        "SELECT s.id, s.sha256, s.filename, p.page_index, p.text FROM scripts s JOIN pages p ON p.script_id = s.id"
        " WHERE s.module_id = ? AND s.kuerzel = ? AND p.label = ? ORDER BY p.page_index LIMIT 1",
        module_id, kuerzel, label,
    )
    cache = settings.data_dir / "folien" / str(row["id"]) / f"{row['page_index']}.png"
    if settings.demo_mode and row["sha256"] == "beispiel":  # Vorschau: Folie aus dem Beispieltext
        return FileResponse(slides.text_png(f"{kuerzel} · Seite {label}", row["text"], cache), media_type="image/png")
    pdf = settings.upload_dir / str(module_id) / f"{row['sha256'][:12]}_{row['filename']}"
    if not pdf.exists():
        raise HTTPException(404, "Das PDF liegt nicht mehr auf dem Server.")
    try:
        png = slides.page_png(pdf, row["page_index"], cache)
    except Exception as e:  # kaputte oder verschlüsselte PDFs
        log.warning("Folie %s S. %s nicht darstellbar: %s", kuerzel, label, e)
        raise HTTPException(404, "Diese Seite lässt sich nicht als Bild darstellen.") from e
    return FileResponse(png, media_type="image/png", headers={"Cache-Control": "private, max-age=86400"})


@app.get("/lectures/{lecture_id}/folie/{kuerzel}/{label}.png", dependencies=[Depends(web_auth)])
def annotated_slide_image(lecture_id: int, kuerzel: str, label: str):
    """Die bemalte Fassung der Skriptseite aus dieser Vorlesung (404, wenn es keine gibt)."""
    page = service.annotated_page(lecture_id, kuerzel, label)
    if not page:
        raise HTTPException(404, "Keine bemalte Folie zu dieser Seite.")
    pdf = service.lecture_slides_path(page)
    if not pdf.exists():
        raise HTTPException(404, "Das PDF liegt nicht mehr auf dem Server.")
    cache = settings.data_dir / "folien-vorlesung" / str(page["slide_id"]) / f"{page['page_index']}.png"
    try:
        png = slides.page_png(pdf, page["page_index"], cache)
    except Exception as e:
        log.warning("Bemalte Folie %s S. %s nicht darstellbar: %s", kuerzel, label, e)
        raise HTTPException(404, "Diese Seite lässt sich nicht als Bild darstellen.") from e
    return FileResponse(png, media_type="image/png", headers={"Cache-Control": "private, max-age=86400"})


@app.get("/vorlesungsfolien/{slide_id}.pdf", dependencies=[Depends(web_auth)])
def lecture_slides_pdf(slide_id: int):
    row = _get("SELECT * FROM lecture_slides WHERE id = ?", slide_id)
    path = service.lecture_slides_path(row)
    if not path.exists():
        raise HTTPException(404, "Das PDF liegt nicht mehr auf dem Server.")
    return FileResponse(path, media_type="application/pdf", filename=row["filename"],
                        content_disposition_type="inline")


@app.post("/lectures/{lecture_id}/vorlesungsfolien", dependencies=[Depends(web_auth)])
def upload_lecture_slides(request: Request, lecture_id: int, files: list[UploadFile] = File(...)):
    lec = _get("SELECT id, module_id FROM lectures WHERE id = ?", lecture_id)
    for f in files:
        _add_lecture_slides(lec["module_id"], f, lecture_id)
    return _redirect(request, f"/lectures/{lecture_id}")


@app.post("/vorlesungsfolien/{slide_id}/zuordnen", dependencies=[Depends(web_auth)])
def assign_lecture_slides(request: Request, slide_id: int, lecture_id: str = Form(""), back: str = Form("/")):
    row = _get("SELECT * FROM lecture_slides WHERE id = ?", slide_id)
    target = int(lecture_id) if lecture_id else None
    if target is not None:
        _get("SELECT id FROM lectures WHERE id = ? AND module_id = ?", target, row["module_id"])
    service.assign_lecture_slides(slide_id, target)
    return _redirect(request, back if back.startswith("/") and not back.startswith("//") else "/")


@app.post("/vorlesungsfolien/{slide_id}/loeschen", dependencies=[Depends(web_auth)])
def delete_lecture_slides(request: Request, slide_id: int, back: str = Form("/")):
    _get("SELECT id FROM lecture_slides WHERE id = ?", slide_id)
    service.delete_lecture_slides(slide_id)
    return _redirect(request, back if back.startswith("/") and not back.startswith("//") else "/")


@app.get("/lectures/{lecture_id}", response_class=HTMLResponse, dependencies=[Depends(web_auth)])
def lecture_page(request: Request, lecture_id: int):
    lec = _get("SELECT l.*, m.name AS module FROM lectures l JOIN modules m ON m.id = l.module_id"
               " WHERE l.id = ?", lecture_id)
    job = service.latest_job(lecture_id)
    notes = service.latest_notes(lecture_id)
    notes_html = render_notes(notes["notes_md"]) if notes else None
    warnings = json.loads(notes["warnings_json"]) if notes and notes.get("warnings_json") else []
    segments = json.loads(lec.pop("segments_json"))
    return templates.TemplateResponse(request, "lecture.html", {
        "lec": lec, "job": job, "notes": notes, "notes_html": notes_html, "warnings": warnings,
        "newer_pending": bool(job and notes and job["id"] != notes["id"]),
        "lecture_slides": service.lecture_slides_of(lecture_id=lecture_id),
        "segments": segments, "b": _budget()})


@app.get("/lectures/{lecture_id}/notizen.md", response_class=PlainTextResponse,
         dependencies=[Depends(web_auth)])
def lecture_notes_md(lecture_id: int):
    job = service.latest_notes(lecture_id)
    if not job:
        raise HTTPException(404, "Noch keine Notizen")
    title = _get("SELECT title FROM lectures WHERE id = ?", lecture_id)["title"]
    filename = quote(f"{title}.md")  # RFC 5987, damit Umlaute im Dateinamen funktionieren
    return PlainTextResponse(job["notes_md"], media_type="text/markdown; charset=utf-8",
                             headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"})


@app.post("/lectures/{lecture_id}/jobs", dependencies=[Depends(web_auth)])
def new_job(request: Request, lecture_id: int):
    _get("SELECT id FROM lectures WHERE id = ?", lecture_id)
    _create_job(lecture_id)
    return _redirect(request, f"/lectures/{lecture_id}")


@app.post("/jobs/{job_id}/submit", dependencies=[Depends(web_auth)])
def submit_job(request: Request, job_id: int):
    job = _get("SELECT * FROM jobs WHERE id = ?", job_id)
    try:
        service.submit_job(job_id)
    except BudgetError:
        pass  # Grund steht im Job und wird angezeigt
    except anthropic.APIError as e:
        service._set(job_id, error=f"Abschicken fehlgeschlagen: {api_error_text(e)}")
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return _redirect(request, f"/lectures/{job['lecture_id']}")


@app.post("/poll", dependencies=[Depends(web_auth)])
def poll_now(request: Request, back: str = Form("/")):
    service.poll_jobs()
    safe = back.startswith("/") and not back.startswith("//")
    return _redirect(request, back if safe else "/")


@app.get("/kosten", response_class=HTMLResponse, dependencies=[Depends(web_auth)])
def usage_page(request: Request):
    rows = _all(
        "SELECT u.*, l.title, l.id AS lecture_id, j.kind FROM usage_log u"
        " LEFT JOIN jobs j ON j.id = u.job_id LEFT JOIN lectures l ON l.id = j.lecture_id"
        " ORDER BY u.id DESC LIMIT 200"
    )
    return templates.TemplateResponse(request, "usage.html", {"rows": rows, "b": _budget()})
