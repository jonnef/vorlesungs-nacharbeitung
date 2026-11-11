"""Kernlogik: Module, Skripte, Vorlesungen und Claude-Jobs mit Budgetkontrolle."""

import hashlib
import json
import logging
import shutil
import threading
from datetime import datetime, timezone
from pathlib import Path

import anthropic
from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
from anthropic.types.messages.batch_create_params import Request

from . import cardcheck, cards, conceptmap, exam, glossary, hints, lecture_slides, pricing
from .config import Settings
from .db import Database, now
from .prompt import build_request, validate_citations
from .scripts import extract_pages, make_kuerzel
from .selection import select_pages

log = logging.getLogger(__name__)


class BudgetError(Exception):
    pass


def api_error_text(e: anthropic.APIError) -> str:
    """Lesbare Fehlermeldung der Claude-API inkl. Begründung und Request-ID."""
    status = getattr(e, "status_code", None)
    body = getattr(e, "body", None)
    detail = ""
    if isinstance(body, dict) and isinstance(body.get("error"), dict):
        err = body["error"]
        detail = f"{err.get('type', '')}: {err.get('message', '')}".strip(": ")
    elif body:
        detail = str(body)
    else:
        response = getattr(e, "response", None)
        detail = (response.text if response is not None else "") or e.message
    request_id = getattr(e, "request_id", None)
    parts = [f"HTTP {status}" if status else type(e).__name__, detail[:500]]
    if request_id:
        parts.append(f"(Request-ID {request_id})")
    return " ".join(p for p in parts if p)


class Service:
    def __init__(self, settings: Settings, db: Database, client: anthropic.Anthropic | None = None):
        self.settings = settings
        self.db = db
        self._client = client
        self._submit_lock = threading.Lock()

    @property
    def client(self) -> anthropic.Anthropic:
        if self._client is None:
            self._client = anthropic.Anthropic()  # liest ANTHROPIC_API_KEY
        return self._client

    # ---------- Module & Skripte ----------

    def get_or_create_module(self, name: str) -> int:
        name = name.strip()
        if not name:
            raise ValueError("Modulname fehlt.")
        with self.db.connect() as conn:
            row = conn.execute("SELECT id FROM modules WHERE name = ?", (name,)).fetchone()
            if row:
                return row["id"]
            return conn.execute(
                "INSERT INTO modules (name, created_at) VALUES (?, ?)", (name, now())
            ).lastrowid

    def add_script(self, module_id: int, filename: str, tmp_path: Path) -> tuple[int, bool]:
        """Speichert ein PDF und extrahiert die Seiten. Rückgabe: (script_id, neu angelegt)."""
        sha = hashlib.sha256(tmp_path.read_bytes()).hexdigest()
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT id FROM scripts WHERE module_id = ? AND sha256 = ?", (module_id, sha)
            ).fetchone()
            if row:
                return row["id"], False
            pages = extract_pages(tmp_path)
            taken = {r["kuerzel"] for r in conn.execute(
                "SELECT kuerzel FROM scripts WHERE module_id = ?", (module_id,))}
            kuerzel = make_kuerzel(filename, taken)
            dest = self.settings.upload_dir / str(module_id) / f"{sha[:12]}_{Path(filename).name}"
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(tmp_path, dest)
            script_id = conn.execute(
                "INSERT INTO scripts (module_id, filename, kuerzel, sha256, page_count, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (module_id, Path(filename).name, kuerzel, sha, len(pages), now()),
            ).lastrowid
            conn.executemany(
                "INSERT INTO pages (script_id, page_index, label, text) VALUES (?, ?, ?, ?)",
                [(script_id, i, label, text) for i, label, text in pages],
            )
            return script_id, True

    def module_pages(self, module_id: int) -> list[dict]:
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT p.id, p.label, p.text, s.kuerzel FROM pages p"
                " JOIN scripts s ON s.id = p.script_id WHERE s.module_id = ?"
                " ORDER BY s.id, p.page_index",
                (module_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    # ---------- Bemalte Folien aus der Vorlesung ----------

    def lecture_slides_path(self, row: dict) -> Path:
        return self.settings.lecture_slides_dir / str(row["module_id"]) / f"{row['sha256'][:12]}_{row['filename']}"

    def add_lecture_slides(self, module_id: int, filename: str, tmp_path: Path,
                           lecture_id: int | None = None) -> dict:
        """Speichert ein PDF mit bemalten Folien; ohne lecture_id über den Dateinamen zugeordnet."""
        sha = hashlib.sha256(tmp_path.read_bytes()).hexdigest()
        with self.db.connect() as conn:
            lectures = [dict(r) for r in conn.execute(
                "SELECT id, title, source_filename FROM lectures WHERE module_id = ?", (module_id,))]
            if lecture_id is None:
                lecture_id = lecture_slides.match_lecture(filename, lectures)
            row = conn.execute("SELECT * FROM lecture_slides WHERE module_id = ? AND sha256 = ?",
                               (module_id, sha)).fetchone()
            if row:
                if lecture_id is not None and row["lecture_id"] != lecture_id:
                    conn.execute("UPDATE lecture_slides SET lecture_id = ? WHERE id = ?", (lecture_id, row["id"]))
                return {"slide_id": row["id"], "lecture_id": lecture_id or row["lecture_id"], "created": False}
            pages = extract_pages(tmp_path)
            row = {"module_id": module_id, "sha256": sha, "filename": Path(filename).name}
            dest = self.lecture_slides_path(row)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(tmp_path, dest)
            slide_id = conn.execute(
                "INSERT INTO lecture_slides (module_id, lecture_id, filename, sha256, page_count, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (module_id, lecture_id, row["filename"], sha, len(pages), now()),
            ).lastrowid
            conn.executemany(
                "INSERT INTO lecture_slide_pages (slide_id, page_index, text) VALUES (?, ?, ?)",
                [(slide_id, i, text) for i, _label, text in pages],
            )
        return {"slide_id": slide_id, "lecture_id": lecture_id, "created": True}

    def assign_lecture_slides(self, slide_id: int, lecture_id: int | None) -> None:
        with self.db.connect() as conn:
            conn.execute("UPDATE lecture_slides SET lecture_id = ? WHERE id = ?", (lecture_id, slide_id))

    def delete_lecture_slides(self, slide_id: int) -> None:
        with self.db.connect() as conn:
            row = conn.execute("SELECT * FROM lecture_slides WHERE id = ?", (slide_id,)).fetchone()
            if not row:
                return
            conn.execute("DELETE FROM lecture_slides WHERE id = ?", (slide_id,))
        self.lecture_slides_path(dict(row)).unlink(missing_ok=True)
        shutil.rmtree(self.settings.data_dir / "folien-vorlesung" / str(slide_id), ignore_errors=True)

    def _assign_unmatched_slides(self, module_id: int) -> None:
        """Noch nicht zugeordnete Folien einer neu hinzugekommenen Vorlesung zuordnen."""
        with self.db.connect() as conn:
            open_slides = conn.execute(
                "SELECT id, filename FROM lecture_slides WHERE module_id = ? AND lecture_id IS NULL",
                (module_id,)).fetchall()
            if not open_slides:
                return
            lectures = [dict(r) for r in conn.execute(
                "SELECT id, title, source_filename FROM lectures WHERE module_id = ?", (module_id,))]
            for s in open_slides:
                lecture_id = lecture_slides.match_lecture(s["filename"], lectures)
                if lecture_id is not None:
                    conn.execute("UPDATE lecture_slides SET lecture_id = ? WHERE id = ?", (lecture_id, s["id"]))

    def lecture_slides_of(self, *, lecture_id: int | None = None, module_id: int | None = None) -> list[dict]:
        """Folien einer Vorlesung bzw. die noch nicht zugeordneten eines Moduls."""
        with self.db.connect() as conn:
            if lecture_id is not None:
                rows = conn.execute("SELECT * FROM lecture_slides WHERE lecture_id = ? ORDER BY id", (lecture_id,))
            else:
                rows = conn.execute("SELECT * FROM lecture_slides WHERE module_id = ? AND lecture_id IS NULL"
                                    " ORDER BY id", (module_id,))
            return [dict(r) for r in rows]

    def annotated_page(self, lecture_id: int, kuerzel: str, label: str) -> dict | None:
        """Bemalte Seite aus der Vorlesung, die zur Skriptseite [Kürzel S. Seite] passt."""
        with self.db.connect() as conn:
            script_page = conn.execute(
                "SELECT p.text, p.page_index, s.page_count FROM pages p JOIN scripts s ON s.id = p.script_id"
                " JOIN lectures l ON l.module_id = s.module_id"
                " WHERE l.id = ? AND s.kuerzel = ? AND p.label = ? ORDER BY p.page_index LIMIT 1",
                (lecture_id, kuerzel, label)).fetchone()
            if not script_page:
                return None
            pages = [dict(r) for r in conn.execute(
                "SELECT ls.id AS slide_id, ls.module_id, ls.sha256, ls.filename, ls.page_count, lp.page_index, lp.text"
                " FROM lecture_slides ls JOIN lecture_slide_pages lp ON lp.slide_id = ls.id"
                " WHERE ls.lecture_id = ? ORDER BY ls.id, lp.page_index", (lecture_id,))]
        return lecture_slides.best_page(script_page["text"], pages, script_page["page_count"],
                                        script_page["page_index"])

    # ---------- Vorlesungen ----------

    def add_lecture(self, module_id: int, title: str, source_filename: str,
                    duration_sec: float, segments: list[dict]) -> int:
        segments = [
            {"start": float(s["start"]), "end": float(s["end"]), "text": str(s.get("text", ""))}
            for s in segments
        ]
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT id FROM lectures WHERE module_id = ? AND source_filename = ?",
                (module_id, source_filename),
            ).fetchone()
            if row:  # erneut hochgeladenes Transkript ersetzt das alte
                conn.execute(
                    "UPDATE lectures SET title = ?, duration_sec = ?, segments_json = ? WHERE id = ?",
                    (title, duration_sec, json.dumps(segments), row["id"]),
                )
                return row["id"]
            lecture_id = conn.execute(
                "INSERT INTO lectures (module_id, title, source_filename, duration_sec,"
                " segments_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (module_id, title, source_filename, duration_sec, json.dumps(segments), now()),
            ).lastrowid
        self._assign_unmatched_slides(module_id)
        return lecture_id

    def latest_job(self, lecture_id: int) -> dict | None:
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM jobs WHERE lecture_id = ? AND kind = 'notes' ORDER BY id DESC LIMIT 1",
                (lecture_id,),
            ).fetchone()
        return dict(row) if row else None

    def latest_notes(self, lecture_id: int) -> dict | None:
        """Neueste fertige Notizen – bleiben sichtbar, während eine neue Fassung entsteht."""
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM jobs WHERE lecture_id = ? AND kind = 'notes' AND status = 'done'"
                " AND notes_md IS NOT NULL ORDER BY id DESC LIMIT 1",
                (lecture_id,),
            ).fetchone()
        return dict(row) if row else None

    def regeneration_plan(self, module_id: int) -> dict:
        """Welche Vorlesungen „Alle Notizen neu erstellen“ anfasst und was es ungefähr kostet.

        Höchstkosten wie bei jedem Job (Input + voll ausgeschöpfter Deckel); die Erwartung
        nimmt die tatsächlichen Kosten der letzten Fassung mal 1,4 (Beispiele und Diagramme
        machen die Notizen länger), ohne bisherige Kosten die Hälfte der Höchstkosten.
        """
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT l.id, l.title, j.status, j.input_tokens_est,"
                " (SELECT COALESCE(SUM(u.cost_usd), 0) FROM usage_log u WHERE u.job_id = j.id) AS cost"
                " FROM lectures l LEFT JOIN jobs j ON j.id ="
                "  (SELECT MAX(id) FROM jobs WHERE lecture_id = l.id AND kind = 'notes')"
                " WHERE l.module_id = ? ORDER BY l.source_filename",
                (module_id,),
            ).fetchall()
        todo, busy = [], []
        worst = expected = 0.0
        for r in rows:
            if r["status"] in ("estimated", "blocked", "submitted"):
                busy.append(dict(r))
                continue
            todo.append(dict(r))
            cap = pricing.worst_case_usd(self.settings.model, r["input_tokens_est"] or 0, self.settings.max_output_tokens)
            worst += cap
            expected += r["cost"] * 1.4 if r["cost"] else cap / 2
        return {"todo": todo, "busy": busy, "worst_usd": worst, "expected_usd": expected,
                "budget_left_usd": self.budget_left_usd()}

    def regenerate_module(self, module_id: int) -> int:
        """Legt für jede Vorlesung des Moduls (ohne laufenden Job) neue Notizen an. Rückgabe: Anzahl."""
        created = 0
        for lec in self.regeneration_plan(module_id)["todo"]:
            self.create_job(lec["id"])
            created += 1
        return created

    # ---------- Budget ----------

    def month_spent_usd(self) -> float:
        month = datetime.now(timezone.utc).strftime("%Y-%m")
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT COALESCE(SUM(cost_usd), 0) AS s FROM usage_log WHERE substr(created_at, 1, 7) = ?",
                (month,),
            ).fetchone()
        return row["s"]

    def reserved_usd(self) -> float:
        """Worst-Case-Kosten der Jobs, die gerade bei Anthropic laufen."""
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT COALESCE(SUM(cost_est_usd), 0) AS s FROM jobs WHERE status = 'submitted'"
            ).fetchone()
        return row["s"]

    def budget_left_usd(self) -> float:
        return self.settings.monthly_budget_usd - self.month_spent_usd() - self.reserved_usd()

    # ---------- Jobs ----------

    def create_job(self, lecture_id: int) -> int:
        """Baut die Anfrage, zählt die Tokens exakt und legt einen Job mit Kostenschätzung an."""
        with self.db.connect() as conn:
            lec = conn.execute("SELECT * FROM lectures WHERE id = ?", (lecture_id,)).fetchone()
        if not lec:
            raise ValueError("Vorlesung nicht gefunden.")
        segments = json.loads(lec["segments_json"])
        pages = select_pages(
            self.module_pages(lec["module_id"]), segments, self.settings.script_context_tokens
        )
        params = build_request(
            model=self.settings.model,
            effort=self.settings.effort,
            max_tokens=self.settings.max_output_tokens,
            title=lec["title"],
            segments=segments,
            pages=pages,
        )
        return self._insert_job(lecture_id, "notes", params,
                                [[p["kuerzel"], p["label"]] for p in pages])

    def _insert_job(self, lecture_id: int, kind: str, params: dict, pages: list,
                    source_job_id: int | None = None, source_ids: list | None = None) -> int:
        """Zählt die Tokens, legt den Job mit Höchstkosten an und startet ihn ggf. automatisch."""
        input_tokens = self._count_tokens(params)
        estimate = pricing.worst_case_usd(params["model"], input_tokens, params["max_tokens"])
        with self.db.connect() as conn:
            job_id = conn.execute(
                "INSERT INTO jobs (lecture_id, kind, source_job_id, source_ids, status, model, request_json,"
                " pages_json, input_tokens_est, cost_est_usd, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, 'estimated', ?, ?, ?, ?, ?, ?, ?)",
                (lecture_id, kind, source_job_id, json.dumps(source_ids) if source_ids is not None else None,
                 params["model"], json.dumps(params),
                 json.dumps(pages), input_tokens, estimate, now(), now()),
            ).lastrowid
        log.info("Job %s (%s): %s Input-Tokens, max. %.3f USD", job_id, kind, input_tokens, estimate)
        if self.settings.auto_submit:
            try:
                self.submit_job(job_id)
            except BudgetError as e:
                log.warning("Job %s nicht gestartet: %s", job_id, e)
            except anthropic.APIError as e:
                # Job bleibt „wartet auf Freigabe“ und kann in der Weboberfläche erneut gestartet werden.
                log.error("Job %s konnte nicht abgeschickt werden: %s", job_id, api_error_text(e))
                self._set(job_id, error=f"Abschicken fehlgeschlagen: {api_error_text(e)}")
        return job_id

    def _count_tokens(self, params: dict) -> int:
        base = {"model": params["model"], "system": params["system"], "messages": params["messages"]}
        try:
            return self.client.messages.count_tokens(
                **base, thinking=params["thinking"], output_config=params["output_config"]
            ).input_tokens
        except anthropic.BadRequestError as e:
            # Falls der Endpunkt thinking/output_config nicht annimmt: ohne zählen. Die
            # Abweichung ist klein (die Kostenschätzung rechnet ohnehin mit dem vollen Deckel).
            log.warning("Token-Zählung mit thinking/effort abgelehnt (%s), zähle ohne.", api_error_text(e))
            return self.client.messages.count_tokens(**base).input_tokens

    # ---------- Glossar ----------

    def ensure_glossary_jobs(self) -> None:
        """Legt für jede fertige Notiz ohne Glossar einen Glossar-Job an (auch für ältere Vorlesungen).

        Läuft im Hintergrund-Worker. Wird eine Vorlesung neu erstellt, bekommt die neue Fassung
        ebenfalls einen Glossar-Job, der die alten Einträge dieser Vorlesung ersetzt.
        """
        with self.db.connect() as conn:
            pending = conn.execute(
                "SELECT n.id, n.lecture_id, n.notes_md, n.pages_json, l.title FROM jobs n"
                " JOIN lectures l ON l.id = n.lecture_id"
                " WHERE n.kind = 'notes' AND n.status = 'done' AND n.notes_md IS NOT NULL"
                " AND n.id = (SELECT MAX(id) FROM jobs WHERE lecture_id = n.lecture_id AND kind = 'notes')"
                " AND NOT EXISTS (SELECT 1 FROM jobs g WHERE g.kind = 'glossary' AND g.source_job_id = n.id)"
            ).fetchall()
            blocked = [r["id"] for r in conn.execute(
                "SELECT id FROM jobs WHERE kind = 'glossary' AND status = 'blocked'")]
        for n in pending:
            params = glossary.build_request(
                model=self.settings.model, effort=self.settings.glossary_effort,
                max_tokens=self.settings.glossary_max_tokens, title=n["title"], notes=n["notes_md"],
            )
            try:
                self._insert_job(n["lecture_id"], "glossary", params, json.loads(n["pages_json"]),
                                 source_job_id=n["id"])
            except anthropic.APIError as e:
                log.warning("Glossar-Job für Vorlesung %s nicht angelegt: %s", n["lecture_id"], api_error_text(e))
                return
        if self.settings.auto_submit:
            for job_id in blocked:  # klein und günstig – bei frei gewordenem Budget nachholen
                try:
                    self.submit_job(job_id)
                except (BudgetError, ValueError, anthropic.APIError):
                    break

    def module_glossary(self, module_id: int) -> list[dict]:
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT g.*, l.title AS lecture_title FROM glossary_entries g"
                " JOIN lectures l ON l.id = g.lecture_id WHERE g.module_id = ?"
                " ORDER BY l.source_filename, g.id",
                (module_id,),
            ).fetchall()
        entries = []
        for r in rows:
            e = dict(r)
            e["timestamps"] = json.loads(e.pop("timestamps_json"))
            e["pages"] = json.loads(e.pop("pages_json"))
            entries.append(e)
        return glossary.group_entries(entries)

    def glossary_status(self, module_id: int) -> dict:
        """Wie viele Vorlesungen im Glossar stecken bzw. noch ausgewertet werden."""
        with self.db.connect() as conn:
            done = conn.execute(
                "SELECT COUNT(DISTINCT lecture_id) AS c FROM glossary_entries WHERE module_id = ?",
                (module_id,)).fetchone()["c"]
            running = conn.execute(
                "SELECT COUNT(*) AS c FROM jobs j JOIN lectures l ON l.id = j.lecture_id"
                " WHERE l.module_id = ? AND j.kind = 'glossary' AND j.status IN ('estimated', 'blocked', 'submitted')",
                (module_id,)).fetchone()["c"]
        return {"lectures": done, "pending": running}

    def _store_glossary(self, job: dict, text: str) -> None:
        with self.db.connect() as conn:
            lec = conn.execute("SELECT module_id, duration_sec FROM lectures WHERE id = ?",
                               (job["lecture_id"],)).fetchone()
            entries = glossary.parse_entries(text, lec["duration_sec"],
                                             {tuple(p) for p in json.loads(job["pages_json"])})
            conn.execute("DELETE FROM glossary_entries WHERE lecture_id = ?", (job["lecture_id"],))
            conn.executemany(
                "INSERT INTO glossary_entries (module_id, lecture_id, job_id, term, norm, kind,"
                " definition, formula, timestamps_json, pages_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [(lec["module_id"], job["lecture_id"], job["id"], e["term"], e["norm"], e["kind"],
                  e["definition"], e["formula"], json.dumps(e["timestamps"]), json.dumps(e["pages"]))
                 for e in entries],
            )
        self._set(job["id"], status="done", error=None)
        log.info("Glossar-Job %s fertig: %d Einträge", job["id"], len(entries))

    # ---------- Prüfungshinweise ----------

    def ensure_hint_jobs(self) -> None:
        """Wertet jede fertige Notiz (neueste Fassung je Vorlesung) einmal auf Prüfungshinweise aus.

        Enthält das Transkript keine einzige Hinweisstelle, wird ohne Claude-Aufruf ein leeres
        Ergebnis gespeichert.
        """
        with self.db.connect() as conn:
            pending = conn.execute(
                "SELECT n.id, n.lecture_id, n.notes_md, n.pages_json, l.title, l.segments_json FROM jobs n"
                " JOIN lectures l ON l.id = n.lecture_id"
                " WHERE n.kind = 'notes' AND n.status = 'done' AND n.notes_md IS NOT NULL"
                " AND n.id = (SELECT MAX(id) FROM jobs WHERE lecture_id = n.lecture_id AND kind = 'notes')"
                " AND NOT EXISTS (SELECT 1 FROM jobs h WHERE h.kind = 'hints' AND h.source_job_id = n.id)"
            ).fetchall()
            blocked = [r["id"] for r in conn.execute("SELECT id FROM jobs WHERE kind = 'hints' AND status = 'blocked'")]
        for n in pending:
            blocks = hints.candidate_blocks(json.loads(n["segments_json"]))
            params = hints.build_request(
                model=self.settings.model, effort=self.settings.hints_effort,
                max_tokens=self.settings.hints_max_tokens, title=n["title"], notes=n["notes_md"], blocks=blocks,
            )
            if not blocks:
                self._empty_hints_job(n["lecture_id"], n["id"], params, json.loads(n["pages_json"]))
                continue
            try:
                self._insert_job(n["lecture_id"], "hints", params, json.loads(n["pages_json"]), source_job_id=n["id"])
            except anthropic.APIError as e:
                log.warning("Prüfungshinweise für Vorlesung %s nicht angelegt: %s", n["lecture_id"], api_error_text(e))
                return
        if self.settings.auto_submit:
            for job_id in blocked:
                try:
                    self.submit_job(job_id)
                except (BudgetError, ValueError, anthropic.APIError):
                    break

    def _empty_hints_job(self, lecture_id: int, notes_job_id: int, params: dict, pages: list) -> None:
        with self.db.connect() as conn:
            job_id = conn.execute(
                "INSERT INTO jobs (lecture_id, kind, source_job_id, status, model, request_json, pages_json,"
                " input_tokens_est, cost_est_usd, created_at, updated_at)"
                " VALUES (?, 'hints', ?, 'done', ?, '{}', ?, 0, 0, ?, ?)",
                (lecture_id, notes_job_id, params["model"], json.dumps(pages), now(), now()),
            ).lastrowid
            conn.execute("DELETE FROM exam_hints WHERE lecture_id = ?", (lecture_id,))
        log.info("Prüfungshinweise (Job %s): keine Hinweisstellen im Transkript", job_id)

    def _store_hints(self, job: dict, text: str) -> None:
        with self.db.connect() as conn:
            lec = conn.execute("SELECT module_id, duration_sec, segments_json FROM lectures WHERE id = ?",
                               (job["lecture_id"],)).fetchone()
            transcript = " ".join(s.get("text", "") for s in json.loads(lec["segments_json"]))
            entries = hints.parse(text, duration_sec=lec["duration_sec"], transcript=transcript,
                                  known_pages={tuple(p) for p in json.loads(job["pages_json"])})
            conn.execute("DELETE FROM exam_hints WHERE lecture_id = ?", (job["lecture_id"],))
            conn.executemany(
                "INSERT INTO exam_hints (module_id, lecture_id, job_id, kind, topic, quote, timestamp, seconds,"
                " pages_json, note, verified) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [(lec["module_id"], job["lecture_id"], job["id"], e["kind"], e["topic"], e["quote"], e["timestamp"],
                  e["seconds"], json.dumps(e["pages"]), e["note"], int(e["verified"])) for e in entries],
            )
        self._set(job["id"], status="done", error=None)
        log.info("Prüfungshinweise (Job %s) fertig: %d Hinweise", job["id"], len(entries))

    def module_hints(self, module_id: int) -> list[dict]:
        """Alle Hinweise des Moduls, chronologisch (Vorlesung, dann Zeitstempel)."""
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT h.*, l.title AS lecture_title FROM exam_hints h JOIN lectures l ON l.id = h.lecture_id"
                " WHERE h.module_id = ? ORDER BY l.source_filename, h.seconds",
                (module_id,),
            ).fetchall()
        result = []
        for r in rows:
            h = dict(r)
            h["pages"] = json.loads(h.pop("pages_json"))
            h["verified"] = bool(h["verified"])
            result.append(h)
        return result

    def hints_status(self, module_id: int) -> dict:
        with self.db.connect() as conn:
            done = conn.execute(
                "SELECT COUNT(DISTINCT j.lecture_id) AS c FROM jobs j JOIN lectures l ON l.id = j.lecture_id"
                " WHERE l.module_id = ? AND j.kind = 'hints' AND j.status = 'done'", (module_id,)).fetchone()["c"]
            running = conn.execute(
                "SELECT COUNT(*) AS c FROM jobs j JOIN lectures l ON l.id = j.lecture_id"
                " WHERE l.module_id = ? AND j.kind = 'hints' AND j.status IN ('estimated', 'blocked', 'submitted')",
                (module_id,)).fetchone()["c"]
        return {"lectures": done, "pending": running}

    # ---------- Lernen: Karteikarten und Übungsaufgaben ----------

    def ensure_card_jobs(self) -> None:
        """Erstellt für jede fertige Notiz (neueste Fassung je Vorlesung) einmal Karten und Aufgaben."""
        with self.db.connect() as conn:
            pending = conn.execute(
                "SELECT n.id, n.lecture_id, n.notes_md, n.pages_json, l.title, l.module_id FROM jobs n"
                " JOIN lectures l ON l.id = n.lecture_id"
                " WHERE n.kind = 'notes' AND n.status = 'done' AND n.notes_md IS NOT NULL"
                " AND n.id = (SELECT MAX(id) FROM jobs WHERE lecture_id = n.lecture_id AND kind = 'notes')"
                " AND NOT EXISTS (SELECT 1 FROM jobs c WHERE c.kind = 'cards' AND c.source_job_id = n.id)"
            ).fetchall()
            blocked = [r["id"] for r in conn.execute("SELECT id FROM jobs WHERE kind = 'cards' AND status = 'blocked'")]
        for n in pending:
            try:
                self._create_card_job(dict(n))
            except anthropic.APIError as e:
                log.warning("Karteikarten für Vorlesung %s nicht angelegt: %s", n["lecture_id"], api_error_text(e))
                return
        if self.settings.auto_submit:
            for job_id in blocked:
                try:
                    self.submit_job(job_id)
                except (BudgetError, ValueError, anthropic.APIError):
                    break

    REPLACE = "ersetzen"  # Markierung in source_ids: alte Karten der Vorlesung werden ersetzt
    OLD_VERSION_REASON = "Alte Fassung: durch neu erstellte Karten ersetzt"

    def _create_card_job(self, n: dict, replace: bool = False) -> int:
        """`n`: Notizen-Job mit lecture_id, notes_md, pages_json, title, module_id (und id)."""
        pages = cards.cited_pages(n["notes_md"], self.module_pages(n["module_id"]), self.settings.cards_script_tokens)
        params = cards.build_request(
            model=self.settings.model, effort=self.settings.cards_effort,
            max_tokens=self.settings.cards_max_tokens, title=n["title"], notes=n["notes_md"], pages=pages,
        )
        return self._insert_job(n["lecture_id"], "cards", params, json.loads(n["pages_json"]), source_job_id=n["id"],
                                source_ids=[self.REPLACE] if replace else None)

    def card_regeneration_plan(self, module_id: int | None = None) -> dict:
        """Vorlesungen mit fertigen Notizen, deren Karten „Neu erstellen“ ersetzen würde, und grobe Kosten."""
        where, args = ("AND l.module_id = ?", [module_id]) if module_id else ("", [])
        with self.db.connect() as conn:
            rows = [dict(r) for r in conn.execute(
                "SELECT n.id, n.lecture_id, n.notes_md, n.pages_json, l.title, l.module_id FROM jobs n"
                " JOIN lectures l ON l.id = n.lecture_id"
                " WHERE n.kind = 'notes' AND n.status = 'done' AND n.notes_md IS NOT NULL"
                " AND n.id = (SELECT MAX(id) FROM jobs WHERE lecture_id = n.lecture_id AND kind = 'notes'"
                "             AND status = 'done' AND notes_md IS NOT NULL)"
                f" AND NOT EXISTS (SELECT 1 FROM jobs c WHERE c.lecture_id = l.id AND c.kind = 'cards'"
                f"                 AND c.status IN ('estimated', 'blocked', 'submitted')) {where}"
                " ORDER BY l.module_id, l.source_filename", args)]
            avg = conn.execute(
                "SELECT AVG(s) AS a FROM (SELECT SUM(u.cost_usd) AS s FROM usage_log u JOIN jobs j ON j.id = u.job_id"
                " WHERE j.kind = 'cards' GROUP BY j.id)").fetchone()["a"]
        return {"lectures": rows, "expected_usd": (avg or 0.2) * len(rows)}

    def regenerate_cards(self, module_id: int | None = None) -> int:
        """Erstellt die Karten der Vorlesungen neu. Noch nie gelernte alte Karten werden ersetzt,
        schon gelernte archiviert (wiederherstellbar). Rückgabe: Anzahl der Aufträge."""
        created = 0
        for n in self.card_regeneration_plan(module_id)["lectures"]:
            self._create_card_job(n, replace=True)
            created += 1
        return created

    def _store_cards(self, job: dict, text: str) -> None:
        """Ersetzt die noch nie gelernten Karten der Vorlesung; schon gelernte bleiben samt Lernstand
        (beim Neu-Erstellen werden sie archiviert)."""
        with self.db.connect() as conn:
            lec = conn.execute("SELECT module_id, duration_sec FROM lectures WHERE id = ?",
                               (job["lecture_id"],)).fetchone()
            items = cards.parse(text, lec["duration_sec"], {tuple(p) for p in json.loads(job["pages_json"])})
            if self.REPLACE in json.loads(job.get("source_ids") or "[]"):
                conn.execute("UPDATE cards SET suspended = 1, archive_reason = ? WHERE lecture_id = ?"
                             " AND last_reviewed IS NOT NULL AND suspended = 0 AND deleted_at IS NULL",
                             (self.OLD_VERSION_REASON, job["lecture_id"]))
            # Gelöschte und archivierte Karten bleiben stehen, damit sie nicht neu entstehen.
            conn.execute("DELETE FROM cards WHERE lecture_id = ? AND last_reviewed IS NULL AND deleted_at IS NULL"
                         " AND suspended = 0", (job["lecture_id"],))
            known = {r["norm"] for r in conn.execute("SELECT norm FROM cards WHERE lecture_id = ?",
                                                     (job["lecture_id"],))}
            new = [c for c in items if c["norm"] not in known]
            conn.executemany(
                "INSERT INTO cards (module_id, lecture_id, job_id, kind, topic, calculator, variants_json, norm,"
                " timestamps_json, pages_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [(lec["module_id"], job["lecture_id"], job["id"], c["kind"], c["topic"], int(c["calculator"]),
                  json.dumps(c["variants"]), c["norm"], json.dumps(c["timestamps"]), json.dumps(c["pages"]), now())
                 for c in new],
            )
        self._set(job["id"], status="done", error=None)
        log.info("Karteikarten (Job %s) fertig: %d neu", job["id"], len(new))

    @staticmethod
    def _card_where(module_id: int | None, kind: str | None, no_calculator: bool) -> tuple[str, list]:
        where, args = ["c.suspended = 0", "c.deleted_at IS NULL"], []
        if module_id:
            where.append("c.module_id = ?")
            args.append(module_id)
        if kind in cards.KINDS:
            where.append("c.kind = ?")
            args.append(kind)
        if no_calculator:
            where.append("c.calculator = 0")
        return " AND ".join(where), args

    def new_cards_left_today(self, today) -> int:
        with self.db.connect() as conn:
            seen = conn.execute("SELECT COUNT(*) AS c FROM card_reviews WHERE first = 1 AND reviewed_on = ?",
                                (today.isoformat(),)).fetchone()["c"]
        return max(0, self.settings.new_cards_per_day - seen)

    def learning_counts(self, today, module_id: int | None = None, kind: str | None = None,
                        no_calculator: bool = False) -> dict:
        """Fällige Wiederholungen, heute noch mögliche neue Karten und Gesamtzahl für die Auswahl."""
        where, args = self._card_where(module_id, kind, no_calculator)
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS total,"
                " COALESCE(SUM(c.last_reviewed IS NOT NULL AND c.due <= ?), 0) AS due,"
                " COALESCE(SUM(c.last_reviewed IS NULL), 0) AS new"
                f" FROM cards c WHERE {where}", [today.isoformat(), *args]).fetchone()
            reviewed = conn.execute("SELECT COUNT(*) AS c FROM card_reviews WHERE reviewed_on = ?",
                                    (today.isoformat(),)).fetchone()["c"]
        return {"total": row["total"], "due": row["due"], "new_total": row["new"],
                "new": min(row["new"], self.new_cards_left_today(today)), "reviewed_today": reviewed}

    def next_card(self, today, module_id: int | None = None, kind: str | None = None,
                  no_calculator: bool = False) -> dict | None:
        """Reihenfolge: fällige Wiederholungen, dann neue Karten (Tageslimit), dann heute vergessene."""
        where, args = self._card_where(module_id, kind, no_calculator)
        t = today.isoformat()
        queries = [
            ("c.last_reviewed IS NOT NULL AND c.due <= ? AND substr(c.last_reviewed, 1, 10) < ?",
             [t, t], "c.due, c.id"),
        ]
        if self.new_cards_left_today(today):
            queries.append(("c.last_reviewed IS NULL", [], "c.lecture_id, c.id"))
        queries.append(("c.last_reviewed IS NOT NULL AND c.due <= ?", [t], "c.last_reviewed, c.id"))
        with self.db.connect() as conn:
            for cond, extra, order in queries:
                row = conn.execute(f"SELECT c.id FROM cards c WHERE {where} AND {cond} ORDER BY {order} LIMIT 1",
                                   [*args, *extra]).fetchone()
                if row:
                    return self.card(row["id"])
        return None

    def card(self, card_id: int) -> dict | None:
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT c.*, l.title AS lecture_title, m.name AS module_name FROM cards c"
                " JOIN lectures l ON l.id = c.lecture_id JOIN modules m ON m.id = c.module_id WHERE c.id = ?",
                (card_id,)).fetchone()
        if not row:
            return None
        c = dict(row)
        c["variants"] = json.loads(c.pop("variants_json"))
        c["timestamps"] = json.loads(c.pop("timestamps_json"))
        c["pages"] = json.loads(c.pop("pages_json"))
        return c

    def review_card(self, card_id: int, grade: int, today) -> dict:
        card = self.card(card_id)
        if not card:
            raise ValueError("Karte nicht gefunden.")
        state = cards.schedule(card, grade, today)
        with self.db.connect() as conn:
            conn.execute(
                "UPDATE cards SET reps = ?, interval_days = ?, ease = ?, lapses = ?, due = ?, views = views + 1,"
                " last_reviewed = ? WHERE id = ?",
                (state["reps"], state["interval_days"], state["ease"], state["lapses"], state["due"],
                 datetime.now().isoformat(timespec="seconds"), card_id))
            conn.execute(
                "INSERT INTO card_reviews (card_id, grade, first, reviewed_on, created_at) VALUES (?, ?, ?, ?, ?)",
                (card_id, grade, int(card["last_reviewed"] is None), today.isoformat(), now()))
        return state

    def set_card_archived(self, card_id: int, archived: bool) -> None:
        """Von Hand archivieren bzw. wiederherstellen; ein automatischer Grund entfällt dabei.
        Wiederhergestellte Karten gelten als geprüft und werden nicht erneut aussortiert."""
        with self.db.connect() as conn:
            conn.execute("UPDATE cards SET suspended = ?, archive_reason = NULL, checked_at = COALESCE(checked_at, ?),"
                         " kept = 1 WHERE id = ?", (int(archived), now(), card_id))

    # ---------- Karten aussortieren ----------

    MAX_CARDS_PER_CHECK = 400

    def _cards_to_check(self, module_id: int) -> list[int]:
        with self.db.connect() as conn:
            return [r["id"] for r in conn.execute(
                "SELECT id FROM cards WHERE module_id = ? AND suspended = 0 AND deleted_at IS NULL"
                " AND checked_at IS NULL ORDER BY id LIMIT ?", (module_id, self.MAX_CARDS_PER_CHECK))]

    def _latest_cardcheck_job(self, module_id: int) -> dict | None:
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT j.* FROM jobs j JOIN lectures l ON l.id = j.lecture_id"
                " WHERE l.module_id = ? AND j.kind = 'cardcheck' ORDER BY j.id DESC LIMIT 1", (module_id,)).fetchone()
        return dict(row) if row else None

    def create_cardcheck_job(self, module_id: int, recheck: bool = False) -> int | None:
        """Prüft die noch nicht geprüften Karten des Moduls; `recheck` nimmt alle aktiven Karten erneut dazu."""
        latest = self._latest_cardcheck_job(module_id)
        if latest and latest["status"] in ("estimated", "blocked", "submitted"):
            return None  # läuft schon
        if recheck:
            with self.db.connect() as conn:
                conn.execute("UPDATE cards SET checked_at = NULL WHERE module_id = ? AND suspended = 0"
                             " AND deleted_at IS NULL AND kept = 0", (module_id,))
        ids = self._cards_to_check(module_id)
        if not ids:
            return None
        items = [self.card(i) for i in ids]
        with self.db.connect() as conn:
            module = conn.execute("SELECT name FROM modules WHERE id = ?", (module_id,)).fetchone()["name"]
        by_lecture: dict[int, list[dict]] = {}
        for h in self.module_hints(module_id):
            by_lecture.setdefault(h["lecture_id"], []).append(h)
        hint_text = "\n".join(f"{hs[0]['lecture_title']}:\n{hints.for_exam_prompt(hs)}" for hs in by_lecture.values())
        params = cardcheck.build_request(model=self.settings.model, effort=self.settings.cardcheck_effort,
                                         max_tokens=self.settings.cardcheck_max_tokens, module=module,
                                         cards=items, hints=hint_text)
        return self._insert_job(items[-1]["lecture_id"], "cardcheck", params, [], source_ids=ids)

    def ensure_cardcheck_jobs(self) -> None:
        """Prüft neue Karten einmal automatisch – sobald im Modul keine Notizen, Karten oder
        Prüfungshinweise mehr entstehen. Ein fehlgeschlagener Lauf wird nicht automatisch wiederholt."""
        with self.db.connect() as conn:
            modules = [r["module_id"] for r in conn.execute(
                "SELECT DISTINCT module_id FROM cards WHERE suspended = 0 AND deleted_at IS NULL AND checked_at IS NULL")]
            busy = {r["module_id"] for r in conn.execute(
                "SELECT DISTINCT l.module_id FROM jobs j JOIN lectures l ON l.id = j.lecture_id"
                " WHERE j.kind IN ('notes', 'cards', 'hints', 'cardcheck')"
                " AND j.status IN ('estimated', 'blocked', 'submitted')")}
            blocked = [r["id"] for r in conn.execute("SELECT id FROM jobs WHERE kind = 'cardcheck' AND status = 'blocked'")]
        if self.settings.auto_submit:
            for job_id in blocked:
                try:
                    self.submit_job(job_id)
                except (BudgetError, ValueError, anthropic.APIError):
                    break
        for module_id in modules:
            if module_id in busy:
                continue
            latest = self._latest_cardcheck_job(module_id)
            if latest and latest["status"] == "failed" and \
                    json.loads(latest["source_ids"] or "[]") == self._cards_to_check(module_id):
                continue
            try:
                self.create_cardcheck_job(module_id)
            except anthropic.APIError as e:
                log.warning("Kartenprüfung für Modul %s nicht angelegt: %s", module_id, api_error_text(e))
                return

    def _store_cardcheck(self, job: dict, text: str) -> None:
        checked = json.loads(job["source_ids"] or "[]")
        flagged = cardcheck.parse(text, set(checked))
        with self.db.connect() as conn:
            # Nur Karten anfassen, die seitdem nicht von Hand geändert oder gelöscht wurden.
            for card_id, reason in flagged.items():
                conn.execute("UPDATE cards SET suspended = 1, archive_reason = ? WHERE id = ? AND suspended = 0"
                             " AND deleted_at IS NULL AND checked_at IS NULL", (reason, card_id))
            conn.executemany("UPDATE cards SET checked_at = ? WHERE id = ? AND checked_at IS NULL",
                             [(now(), i) for i in checked])
        self._set(job["id"], status="done", error=None)
        log.info("Kartenprüfung (Job %s): %d von %d Karten aussortiert", job["id"], len(flagged), len(checked))

    def cardcheck_status(self, module_id: int | None = None) -> dict:
        """Laufende Prüfungen und Zahl automatisch aussortierter Karten (für „Karten verwalten“)."""
        where, args = ("AND l.module_id = ?", [module_id]) if module_id else ("", [])
        cwhere = "AND module_id = ?" if module_id else ""
        with self.db.connect() as conn:
            running = conn.execute(
                "SELECT COUNT(*) AS c FROM jobs j JOIN lectures l ON l.id = j.lecture_id WHERE j.kind = 'cardcheck'"
                f" AND j.status IN ('estimated', 'blocked', 'submitted') {where}", args).fetchone()["c"]
            failed = conn.execute(
                "SELECT j.error FROM jobs j JOIN lectures l ON l.id = j.lecture_id WHERE j.kind = 'cardcheck'"
                f" {where} ORDER BY j.id DESC LIMIT 1", args).fetchone()
            sorted_out = conn.execute(
                "SELECT COUNT(*) AS c FROM cards WHERE archive_reason IS NOT NULL AND suspended = 1"
                f" AND archive_reason != ? AND deleted_at IS NULL {cwhere}",
                [self.OLD_VERSION_REASON, *args]).fetchone()["c"]
            unchecked = conn.execute(
                "SELECT COUNT(*) AS c FROM cards WHERE checked_at IS NULL AND suspended = 0"
                f" AND deleted_at IS NULL {cwhere}", args).fetchone()["c"]
        return {"running": running, "sorted_out": sorted_out, "unchecked": unchecked,
                "error": failed["error"] if failed else None}

    def delete_card(self, card_id: int) -> None:
        """Endgültig löschen: aus Lernen, Archiv und Listen entfernen; der Merker verhindert,
        dass die Karte bei einer neuen Fassung der Notizen wieder entsteht."""
        with self.db.connect() as conn:
            conn.execute("UPDATE cards SET deleted_at = ?, suspended = 0 WHERE id = ?", (now(), card_id))

    def list_cards(self, module_id: int | None = None, archived: bool = False) -> list[dict]:
        """Alle Karten (aktiv oder archiviert) für die Verwaltung, nach Modul und Vorlesung sortiert."""
        where, args = ["c.deleted_at IS NULL", "c.suspended = ?"], [int(archived)]
        if module_id:
            where.append("c.module_id = ?")
            args.append(module_id)
        with self.db.connect() as conn:
            ids = [r["id"] for r in conn.execute(
                "SELECT c.id FROM cards c JOIN lectures l ON l.id = c.lecture_id JOIN modules m ON m.id = c.module_id"
                f" WHERE {' AND '.join(where)} ORDER BY m.name, l.source_filename, c.id", args)]
        return [self.card(i) for i in ids]

    def learning_modules(self, today) -> list[dict]:
        """Übersicht je Modul: Karten, Aufgaben, fällig, neu, ausgesetzt."""
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT m.id, m.name,"
                " COALESCE(SUM(c.kind = 'karte' AND c.suspended = 0), 0) AS karten,"
                " COALESCE(SUM(c.kind = 'aufgabe' AND c.suspended = 0), 0) AS aufgaben,"
                " COALESCE(SUM(c.suspended = 0 AND c.last_reviewed IS NOT NULL AND c.due <= ?), 0) AS due,"
                " COALESCE(SUM(c.suspended = 0 AND c.last_reviewed IS NULL), 0) AS new,"
                " COALESCE(SUM(c.suspended), 0) AS suspended"
                " FROM modules m JOIN cards c ON c.module_id = m.id AND c.deleted_at IS NULL"
                " GROUP BY m.id ORDER BY m.name",
                (today.isoformat(),)).fetchall()
        return [dict(r) for r in rows]

    def cards_status(self, module_id: int) -> dict:
        with self.db.connect() as conn:
            total = conn.execute("SELECT COUNT(*) AS c FROM cards WHERE module_id = ? AND suspended = 0"
                                 " AND deleted_at IS NULL",
                                 (module_id,)).fetchone()["c"]
            running = conn.execute(
                "SELECT COUNT(*) AS c FROM jobs j JOIN lectures l ON l.id = j.lecture_id"
                " WHERE l.module_id = ? AND j.kind = 'cards' AND j.status IN ('estimated', 'blocked', 'submitted')",
                (module_id,)).fetchone()["c"]
        return {"total": total, "pending": running}

    def archived_count(self, module_id: int | None = None) -> int:
        sql = "SELECT COUNT(*) AS c FROM cards WHERE suspended = 1 AND deleted_at IS NULL"
        args: list = []
        if module_id:
            sql += " AND module_id = ?"
            args.append(module_id)
        with self.db.connect() as conn:
            return conn.execute(sql, args).fetchone()["c"]

    # ---------- Concept Map ----------

    def _conceptmap_sources(self, module_id: int) -> list[list[int]]:
        """[[lecture_id, glossary_job_id], …] der Glossareinträge, aus denen die Map entsteht."""
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT g.lecture_id, MAX(g.job_id) AS job_id FROM glossary_entries g"
                " JOIN lectures l ON l.id = g.lecture_id WHERE g.module_id = ?"
                " GROUP BY g.lecture_id ORDER BY MIN(l.source_filename)", (module_id,)).fetchall()
        return [[r["lecture_id"], r["job_id"]] for r in rows]

    def latest_conceptmap_job(self, module_id: int) -> dict | None:
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT j.* FROM jobs j JOIN lectures l ON l.id = j.lecture_id"
                " WHERE l.module_id = ? AND j.kind = 'conceptmap' ORDER BY j.id DESC LIMIT 1", (module_id,)).fetchone()
        return dict(row) if row else None

    def create_conceptmap_job(self, module_id: int) -> int | None:
        sources = self._conceptmap_sources(module_id)
        groups = self.module_glossary(module_id)
        if not sources or len(groups) < 2:
            return None
        with self.db.connect() as conn:
            module = conn.execute("SELECT name FROM modules WHERE id = ?", (module_id,)).fetchone()["name"]
        params = conceptmap.build_request(model=self.settings.model, effort=self.settings.conceptmap_effort,
                                          max_tokens=self.settings.conceptmap_max_tokens, module=module, groups=groups,
                                          max_terms=self.settings.conceptmap_max_terms)
        return self._insert_job(sources[-1][0], "conceptmap", params, [], source_ids=sources)

    def ensure_conceptmap_jobs(self) -> None:
        """Erstellt die Concept Map neu, sobald neue Glossareinträge da sind.

        Wartet wie die Klausurvorbereitung, solange im Modul noch Notizen oder Glossare
        entstehen, damit nicht für jede Vorlesung eines Stapels eine eigene Fassung entsteht.
        """
        with self.db.connect() as conn:
            modules = [r["id"] for r in conn.execute("SELECT id FROM modules")]
            busy = {r["module_id"] for r in conn.execute(
                "SELECT DISTINCT l.module_id FROM jobs j JOIN lectures l ON l.id = j.lecture_id"
                " WHERE j.kind IN ('notes', 'glossary') AND j.status IN ('estimated', 'blocked', 'submitted')")}
        for module_id in modules:
            if module_id in busy:
                continue
            sources = self._conceptmap_sources(module_id)
            if not sources:
                continue
            latest = self.latest_conceptmap_job(module_id)
            if latest and json.loads(latest["source_ids"] or "[]") == sources \
                    and not self._conceptmap_retry_allowed(latest):
                if latest["status"] == "blocked" and self.settings.auto_submit:
                    try:
                        self.submit_job(latest["id"])
                    except (BudgetError, ValueError, anthropic.APIError):
                        pass
                continue
            try:
                self.create_conceptmap_job(module_id)
            except anthropic.APIError as e:
                log.warning("Concept Map für Modul %s nicht angelegt: %s", module_id, api_error_text(e))
                return

    def _conceptmap_retry_allowed(self, job: dict) -> bool:
        """Ein am Token-Deckel gescheiterter Versuch wird einmal wiederholt, sobald der Deckel höher ist.
        Andere Fehler werden nicht automatisch wiederholt (sonst entstünden laufend Kosten)."""
        if job["status"] != "failed" or "Token-Deckel" not in (job["error"] or ""):
            return False
        return json.loads(job["request_json"]).get("max_tokens", 0) < self.settings.conceptmap_max_tokens

    def _store_conceptmap(self, job: dict, text: str) -> None:
        with self.db.connect() as conn:
            module_id = conn.execute("SELECT module_id FROM lectures WHERE id = ?",
                                     (job["lecture_id"],)).fetchone()["module_id"]
            known = {r["norm"] for r in conn.execute("SELECT DISTINCT norm FROM glossary_entries WHERE module_id = ?",
                                                     (module_id,))}
        data, warnings = conceptmap.parse(text, known)
        self._set(job["id"], status="done", notes_md=json.dumps(data, ensure_ascii=False),
                  warnings_json=json.dumps(warnings), error=None)
        log.info("Concept Map (Job %s) fertig: %d Begriffe, %d Beziehungen",
                 job["id"], len(data["nodes"]), len(data["edges"]))

    def module_conceptmap(self, module_id: int) -> dict:
        """Neueste fertige Concept Map (für die Seite aufbereitet) und Status der neuesten Fassung."""
        latest = self.latest_conceptmap_job(module_id)
        with self.db.connect() as conn:
            done = conn.execute(
                "SELECT j.* FROM jobs j JOIN lectures l ON l.id = j.lecture_id WHERE l.module_id = ?"
                " AND j.kind = 'conceptmap' AND j.status = 'done' ORDER BY j.id DESC LIMIT 1", (module_id,)).fetchone()
            lectures = [dict(r) for r in conn.execute(
                "SELECT id, title FROM lectures WHERE module_id = ? ORDER BY source_filename", (module_id,))]
        result = {"latest": latest, "map": None, "warnings": [], "updated_at": None}
        if done and done["notes_md"]:
            result.update(map=conceptmap.view(json.loads(done["notes_md"]), self.module_glossary(module_id), lectures),
                          warnings=json.loads(done["warnings_json"] or "[]"), updated_at=done["updated_at"])
        return result

    # ---------- Klausurvorbereitung ----------

    def exam_lectures(self, module_id: int) -> list[dict]:
        """Vorlesungen des Moduls mit fertigen Notizen (jeweils die neueste Fassung), in Reihenfolge."""
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT l.id, l.title, l.duration_sec, l.segments_json, n.id AS notes_job_id, n.notes_md,"
                " (SELECT MAX(h.id) FROM jobs h WHERE h.kind = 'hints' AND h.source_job_id = n.id"
                "  AND h.status IN ('done', 'failed')) AS hints_job_id"
                " FROM lectures l JOIN jobs n ON n.lecture_id = l.id AND n.kind = 'notes'"
                "  AND n.id = (SELECT MAX(id) FROM jobs WHERE lecture_id = l.id AND kind = 'notes'"
                "              AND status = 'done' AND notes_md IS NOT NULL)"
                " WHERE l.module_id = ?"
                " ORDER BY l.source_filename",
                (module_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def latest_exam_job(self, module_id: int) -> dict | None:
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT j.* FROM jobs j JOIN lectures l ON l.id = j.lecture_id"
                " WHERE l.module_id = ? AND j.kind = 'exam' ORDER BY j.id DESC LIMIT 1",
                (module_id,),
            ).fetchone()
        return dict(row) if row else None

    def create_exam_job(self, module_id: int) -> int | None:
        lectures = self.exam_lectures(module_id)
        if not lectures:
            return None
        with self.db.connect() as conn:
            module = conn.execute("SELECT name FROM modules WHERE id = ?", (module_id,)).fetchone()["name"]
        by_lecture: dict[int, list[dict]] = {}
        for h in self.module_hints(module_id):
            by_lecture.setdefault(h["lecture_id"], []).append(h)
        params = exam.build_request(
            model=self.settings.model, effort=self.settings.exam_effort,
            max_tokens=self.settings.exam_max_tokens, module=module,
            lectures=[{"title": l["title"], "notes": l["notes_md"], "segments": json.loads(l["segments_json"]),
                       "hints": hints.for_exam_prompt(by_lecture.get(l["id"], []))}
                      for l in lectures],
        )
        return self._insert_job(lectures[-1]["id"], "exam", params, [], source_ids=self._exam_sources(lectures))

    @staticmethod
    def _exam_sources(lectures: list[dict]) -> list[list]:
        return [[l["id"], l["notes_job_id"], l["hints_job_id"]] for l in lectures]

    def ensure_exam_jobs(self) -> None:
        """Erstellt die Klausurvorbereitung neu, sobald neue Notizen fertig sind.

        Wartet, solange im Modul noch Notizen entstehen (auch wenn sie auf Budget oder
        Freigabe warten), damit nicht für jede einzelne Vorlesung eines Stapels – etwa nach
        „Alle Notizen neu erstellen“ – eine eigene, kostenpflichtige Fassung entsteht.
        """
        with self.db.connect() as conn:
            modules = [r["id"] for r in conn.execute("SELECT id FROM modules")]
            busy = {r["module_id"] for r in conn.execute(
                "SELECT DISTINCT l.module_id FROM jobs j JOIN lectures l ON l.id = j.lecture_id"
                " WHERE (j.kind = 'notes' AND j.status IN ('estimated', 'blocked', 'submitted'))"
                "    OR (j.kind = 'hints' AND j.status IN ('estimated', 'blocked', 'submitted'))")}
        for module_id in modules:
            if module_id in busy:
                continue
            lectures = self.exam_lectures(module_id)
            if not lectures or any(l["hints_job_id"] is None for l in lectures):
                continue  # erst die Prüfungshinweise aller Vorlesungen abwarten
            sources = self._exam_sources(lectures)
            latest = self.latest_exam_job(module_id)
            if latest and json.loads(latest["source_ids"] or "[]") == sources:
                if latest["status"] == "blocked" and self.settings.auto_submit:
                    try:
                        self.submit_job(latest["id"])
                    except (BudgetError, ValueError, anthropic.APIError):
                        pass
                continue
            try:
                self.create_exam_job(module_id)
            except anthropic.APIError as e:
                log.warning("Klausurvorbereitung für Modul %s nicht angelegt: %s", module_id, api_error_text(e))
                return

    def module_exam(self, module_id: int) -> dict:
        """Aktuelle Klausurvorbereitung (neueste fertige Fassung) und Status der neuesten Fassung."""
        latest = self.latest_exam_job(module_id)
        with self.db.connect() as conn:
            done = conn.execute(
                "SELECT j.* FROM jobs j JOIN lectures l ON l.id = j.lecture_id"
                " WHERE l.module_id = ? AND j.kind = 'exam' AND j.status = 'done' ORDER BY j.id DESC LIMIT 1",
                (module_id,),
            ).fetchone()
            lectures = []
            if done:
                for lecture_id, *_ in json.loads(done["source_ids"] or "[]"):
                    row = conn.execute("SELECT id, title FROM lectures WHERE id = ?", (lecture_id,)).fetchone()
                    lectures.append(dict(row) if row else {"id": None, "title": "(gelöscht)"})
        return {
            "markdown": done["notes_md"] if done else None,
            "warnings": json.loads(done["warnings_json"] or "[]") if done else [],
            "updated_at": done["updated_at"] if done else None,
            "lectures": lectures,
            "latest": latest,
        }

    def submit_job(self, job_id: int) -> None:
        # Budgetprüfung und Abschicken nicht parallel, sonst könnten zwei Jobs dasselbe Restbudget nutzen.
        with self._submit_lock:
            self._submit_job(job_id)

    def _submit_job(self, job_id: int) -> None:
        with self.db.connect() as conn:
            job = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if not job:
            raise ValueError("Job nicht gefunden.")
        if job["status"] not in ("estimated", "blocked"):
            raise ValueError(f"Job ist bereits im Status {job['status']}.")
        left = self.budget_left_usd()
        if job["cost_est_usd"] > left:
            self._set(job_id, status="blocked", error=(
                f"Monatsbudget reicht nicht: Job bis {job['cost_est_usd']:.2f} USD,"
                f" verfügbar {left:.2f} USD."))
            raise BudgetError(f"Budget reicht nicht ({left:.2f} USD verfügbar).")
        params = json.loads(job["request_json"])
        batch = self.client.messages.batches.create(
            requests=[Request(custom_id=f"job-{job_id}", params=MessageCreateParamsNonStreaming(**params))]
        )
        self._set(job_id, status="submitted", batch_id=batch.id, error=None)
        log.info("Job %s abgeschickt (Batch %s)", job_id, batch.id)

    def poll_jobs(self) -> None:
        """Fragt laufende Batches ab und speichert fertige Notizen samt tatsächlichen Kosten."""
        with self.db.connect() as conn:
            jobs = conn.execute("SELECT * FROM jobs WHERE status = 'submitted'").fetchall()
        for job in jobs:
            try:
                batch = self.client.messages.batches.retrieve(job["batch_id"])
                if batch.processing_status != "ended":
                    continue
                found = False
                for result in self.client.messages.batches.results(job["batch_id"]):
                    if result.custom_id == f"job-{job['id']}":
                        found = True
                        self._store_result(dict(job), result.result)
                if not found:
                    self._set(job["id"], status="failed", error="Batch beendet, aber kein Ergebnis gefunden.")
            except anthropic.APIConnectionError as e:
                log.warning("Keine Verbindung zu Anthropic: %s", e)
                return
            except anthropic.APIStatusError as e:
                log.error("Fehler beim Abfragen von Job %s: %s", job["id"], api_error_text(e))

    def _store_result(self, job: dict, result) -> None:
        if result.type != "succeeded":
            detail = getattr(getattr(result, "error", None), "error", None)
            self._set(job["id"], status="failed", error=f"Batch-Ergebnis: {result.type} {detail or ''}".strip())
            return
        msg = result.message
        u = msg.usage
        cost = pricing.cost_usd(
            job["model"], u.input_tokens, u.output_tokens,
            u.cache_creation_input_tokens or 0, u.cache_read_input_tokens or 0,
        )
        with self.db.connect() as conn:
            conn.execute(
                "INSERT INTO usage_log (job_id, model, input_tokens, output_tokens,"
                " cache_creation_tokens, cache_read_tokens, cost_usd, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (job["id"], msg.model, u.input_tokens, u.output_tokens,
                 u.cache_creation_input_tokens or 0, u.cache_read_input_tokens or 0, cost, now()),
            )
        if msg.stop_reason == "refusal":
            self._set(job["id"], status="failed", error="Claude hat die Anfrage abgelehnt (refusal).")
            return
        text = "".join(b.text for b in msg.content if b.type == "text").strip()
        if job["kind"] == "glossary":
            if msg.stop_reason == "max_tokens":
                self._set(job["id"], status="failed",
                          error="Glossar beim Token-Deckel abgeschnitten (GLOSSARY_MAX_TOKENS erhöhen).")
                return
            try:
                self._store_glossary(job, text)
            except (json.JSONDecodeError, AttributeError) as e:
                self._set(job["id"], status="failed", error=f"Glossar-Antwort nicht lesbar: {e}")
            return
        if job["kind"] == "hints":
            if msg.stop_reason == "max_tokens":
                self._set(job["id"], status="failed",
                          error="Prüfungshinweise beim Token-Deckel abgeschnitten (HINTS_MAX_TOKENS erhöhen).")
                return
            try:
                self._store_hints(job, text)
            except (json.JSONDecodeError, AttributeError) as e:
                self._set(job["id"], status="failed", error=f"Antwort nicht lesbar: {e}")
            return
        if job["kind"] == "conceptmap":
            if msg.stop_reason == "max_tokens":
                self._set(job["id"], status="failed",
                          error="Concept Map beim Token-Deckel abgeschnitten (CONCEPTMAP_MAX_TOKENS erhöhen).")
                return
            try:
                self._store_conceptmap(job, text)
            except (json.JSONDecodeError, AttributeError, TypeError) as e:
                self._set(job["id"], status="failed", error=f"Antwort nicht lesbar: {e}")
            return
        if job["kind"] == "cardcheck":
            if msg.stop_reason == "max_tokens":
                self._set(job["id"], status="failed",
                          error="Kartenprüfung beim Token-Deckel abgeschnitten (CARDCHECK_MAX_TOKENS erhöhen).")
                return
            try:
                self._store_cardcheck(job, text)
            except (json.JSONDecodeError, AttributeError, TypeError) as e:
                self._set(job["id"], status="failed", error=f"Antwort nicht lesbar: {e}")
            return
        if job["kind"] == "cards":
            if msg.stop_reason == "max_tokens":
                self._set(job["id"], status="failed",
                          error="Karteikarten beim Token-Deckel abgeschnitten (CARDS_MAX_TOKENS erhöhen).")
                return
            try:
                self._store_cards(job, text)
            except (json.JSONDecodeError, AttributeError) as e:
                self._set(job["id"], status="failed", error=f"Antwort nicht lesbar: {e}")
            return
        if job["kind"] == "exam":
            sources = json.loads(job["source_ids"] or "[]")
            with self.db.connect() as conn:
                lectures = [dict(conn.execute("SELECT title, duration_sec FROM lectures WHERE id = ?",
                                              (lecture_id,)).fetchone() or {"title": "?", "duration_sec": 0})
                            for lecture_id, *_ in sources]
            warnings = exam.validate(text, lectures)
            if msg.stop_reason == "max_tokens":
                warnings.insert(0, "Antwort wurde beim Token-Deckel abgeschnitten (EXAM_MAX_TOKENS erhöhen).")
            self._set(job["id"], status="done", notes_md=text, warnings_json=json.dumps(warnings), error=None)
            log.info("Klausurvorbereitung (Job %s) fertig, %.3f USD", job["id"], cost)
            return
        notes = text
        with self.db.connect() as conn:
            duration = conn.execute(
                "SELECT duration_sec FROM lectures WHERE id = ?", (job["lecture_id"],)
            ).fetchone()["duration_sec"]
        known = {tuple(p) for p in json.loads(job["pages_json"])}
        warnings = validate_citations(notes, duration, known)
        if msg.stop_reason == "max_tokens":
            warnings.insert(0, "Antwort wurde beim Token-Deckel abgeschnitten (MAX_OUTPUT_TOKENS erhöhen).")
        self._set(job["id"], status="done", notes_md=notes, warnings_json=json.dumps(warnings), error=None)
        log.info("Job %s fertig, %.3f USD", job["id"], cost)
        # Das Glossar dieser Fassung legt der Hintergrund-Worker an (ensure_glossary_jobs).

    def _set(self, job_id: int, **fields) -> None:
        fields["updated_at"] = now()
        cols = ", ".join(f"{k} = ?" for k in fields)
        with self.db.connect() as conn:
            conn.execute(f"UPDATE jobs SET {cols} WHERE id = ?", (*fields.values(), job_id))
