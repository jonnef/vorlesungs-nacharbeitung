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

from . import pricing
from .config import Settings
from .db import Database, now
from .prompt import build_request, validate_citations
from .scripts import extract_pages, make_kuerzel
from .selection import select_pages

log = logging.getLogger(__name__)


class BudgetError(Exception):
    pass


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
            return conn.execute(
                "INSERT INTO lectures (module_id, title, source_filename, duration_sec,"
                " segments_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (module_id, title, source_filename, duration_sec, json.dumps(segments), now()),
            ).lastrowid

    def latest_job(self, lecture_id: int) -> dict | None:
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM jobs WHERE lecture_id = ? ORDER BY id DESC LIMIT 1", (lecture_id,)
            ).fetchone()
        return dict(row) if row else None

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
        counted = self.client.messages.count_tokens(
            model=params["model"],
            system=params["system"],
            messages=params["messages"],
            thinking=params["thinking"],
            output_config=params["output_config"],
        )
        input_tokens = counted.input_tokens
        estimate = pricing.worst_case_usd(params["model"], input_tokens, params["max_tokens"])
        with self.db.connect() as conn:
            job_id = conn.execute(
                "INSERT INTO jobs (lecture_id, status, model, request_json, pages_json,"
                " input_tokens_est, cost_est_usd, created_at, updated_at)"
                " VALUES (?, 'estimated', ?, ?, ?, ?, ?, ?, ?)",
                (lecture_id, params["model"], json.dumps(params),
                 json.dumps([[p["kuerzel"], p["label"]] for p in pages]),
                 input_tokens, estimate, now(), now()),
            ).lastrowid
        log.info("Job %s: %s Input-Tokens, max. %.3f USD", job_id, input_tokens, estimate)
        if self.settings.auto_submit:
            try:
                self.submit_job(job_id)
            except BudgetError as e:
                log.warning("Job %s nicht gestartet: %s", job_id, e)
        return job_id

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
                log.error("Fehler beim Abfragen von Job %s: %s", job["id"], e)

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
        notes = "".join(b.text for b in msg.content if b.type == "text").strip()
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

    def _set(self, job_id: int, **fields) -> None:
        fields["updated_at"] = now()
        cols = ", ".join(f"{k} = ?" for k in fields)
        with self.db.connect() as conn:
            conn.execute(f"UPDATE jobs SET {cols} WHERE id = ?", (*fields.values(), job_id))
