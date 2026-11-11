"""Einstellungen aus Umgebungsvariablen (bzw. der Datei `.env` neben `server/`)."""

import os
from dataclasses import dataclass, field
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv(BASE_DIR / ".env")


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


@dataclass
class Settings:
    data_dir: Path = field(default_factory=lambda: Path(_env("DATA_DIR", str(BASE_DIR / "data"))))
    # Token, mit dem sich der Mac-Watcher an der API anmeldet.
    api_token: str = field(default_factory=lambda: _env("API_TOKEN", ""))
    # Optionales Passwort für die Weboberfläche (HTTP Basic Auth, Benutzername beliebig).
    web_password: str = field(default_factory=lambda: _env("WEB_PASSWORD", ""))

    model: str = field(default_factory=lambda: _env("CLAUDE_MODEL", "claude-opus-5"))
    effort: str = field(default_factory=lambda: _env("CLAUDE_EFFORT", "high"))
    # Deckel für Antwort inkl. Denkprozess – geht als Worst Case in die Kostenschätzung ein.
    max_output_tokens: int = field(default_factory=lambda: int(_env("MAX_OUTPUT_TOKENS", "32000")))
    # Wie viele Tokens an Skriptseiten maximal pro Vorlesung mitgeschickt werden.
    script_context_tokens: int = field(default_factory=lambda: int(_env("SCRIPT_CONTEXT_TOKENS", "60000")))

    # Glossar-Auswertung der fertigen Notizen (klein, daher mittlerer Aufwand reicht).
    glossary_effort: str = field(default_factory=lambda: _env("GLOSSARY_EFFORT", "medium"))
    glossary_max_tokens: int = field(default_factory=lambda: int(_env("GLOSSARY_MAX_TOKENS", "10000")))

    # Prüfungshinweise pro Vorlesung (wertet nur Transkript-Stellen rund um Hinweiswörter aus).
    hints_effort: str = field(default_factory=lambda: _env("HINTS_EFFORT", "medium"))
    hints_max_tokens: int = field(default_factory=lambda: int(_env("HINTS_MAX_TOKENS", "8000")))

    # Klausurvorbereitung pro Modul (fasst alle Notizen zusammen).
    exam_effort: str = field(default_factory=lambda: _env("EXAM_EFFORT", "high"))
    exam_max_tokens: int = field(default_factory=lambda: int(_env("EXAM_MAX_TOKENS", "32000")))

    # Concept Map pro Modul (aus den Glossareinträgen).
    conceptmap_effort: str = field(default_factory=lambda: _env("CONCEPTMAP_EFFORT", "medium"))
    # Deckel inkl. Denkprozess; große Module brauchen Platz für viele Begriffe und Kanten.
    conceptmap_max_tokens: int = field(default_factory=lambda: int(_env("CONCEPTMAP_MAX_TOKENS", "32000")))
    # Höchstens so viele Begriffe auf der Map – bei größeren Glossaren die zentralen.
    conceptmap_max_terms: int = field(default_factory=lambda: int(_env("CONCEPTMAP_MAX_TERMS", "80")))

    # Karteikarten und Übungsaufgaben pro Vorlesung (aus Notizen + zitierten Skriptseiten).
    cards_effort: str = field(default_factory=lambda: _env("CARDS_EFFORT", "medium"))
    cards_max_tokens: int = field(default_factory=lambda: int(_env("CARDS_MAX_TOKENS", "20000")))
    cards_script_tokens: int = field(default_factory=lambda: int(_env("CARDS_SCRIPT_TOKENS", "15000")))
    # Automatisches Aussortieren (Organisatorisches, laut Dozent nicht klausurrelevant).
    cardcheck_effort: str = field(default_factory=lambda: _env("CARDCHECK_EFFORT", "medium"))
    cardcheck_max_tokens: int = field(default_factory=lambda: int(_env("CARDCHECK_MAX_TOKENS", "8000")))
    # Antworten beim Lernen prüfen (sofort, ohne Batch-Rabatt): Karteikarten-Antworten und Fotos
    # vom Rechenweg. Foto-Modell leer = dasselbe wie ANSWER_CHECK_MODEL.
    answer_check_model: str = field(default_factory=lambda: _env("ANSWER_CHECK_MODEL", "claude-haiku-5-5"))
    answer_photo_model: str = field(default_factory=lambda: _env("ANSWER_PHOTO_MODEL", ""))
    answer_check_effort: str = field(default_factory=lambda: _env("ANSWER_CHECK_EFFORT", "low"))
    answer_check_max_tokens: int = field(default_factory=lambda: int(_env("ANSWER_CHECK_MAX_TOKENS", "4000")))
    # Wie viele neue Karten pro Tag beim Lernen dazukommen (über alle Module).
    new_cards_per_day: int = field(default_factory=lambda: int(_env("NEW_CARDS_PER_DAY", "20")))

    monthly_budget_usd: float = field(default_factory=lambda: float(_env("MONTHLY_BUDGET_USD", "10")))
    # Jobs automatisch abschicken, wenn sie ins Budget passen (sonst Freigabe per Klick).
    auto_submit: bool = field(default_factory=lambda: _env("AUTO_SUBMIT", "1") == "1")
    # Öffentliche Vorschau: schreibgeschützt, Beispieldaten, kein Claude, keine API.
    demo_mode: bool = field(default_factory=lambda: _env("DEMO_MODE", "0") == "1")
    # Wohin „Anmelden“ im Hinweisbalken der Vorschau führt.
    demo_login_url: str = field(default_factory=lambda: _env("DEMO_LOGIN_URL", "/vorlesungen/"))
    poll_interval_sec: int = field(default_factory=lambda: int(_env("POLL_INTERVAL_SEC", "60")))

    @property
    def db_path(self) -> Path:
        return self.data_dir / "app.db"

    @property
    def upload_dir(self) -> Path:
        return self.data_dir / "skripte"

    @property
    def lecture_slides_dir(self) -> Path:
        return self.data_dir / "vorlesungsfolien"


settings = Settings()
