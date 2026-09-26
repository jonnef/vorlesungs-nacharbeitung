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
    max_output_tokens: int = field(default_factory=lambda: int(_env("MAX_OUTPUT_TOKENS", "20000")))
    # Wie viele Tokens an Skriptseiten maximal pro Vorlesung mitgeschickt werden.
    script_context_tokens: int = field(default_factory=lambda: int(_env("SCRIPT_CONTEXT_TOKENS", "60000")))

    # Glossar-Auswertung der fertigen Notizen (klein, daher mittlerer Aufwand reicht).
    glossary_effort: str = field(default_factory=lambda: _env("GLOSSARY_EFFORT", "medium"))
    glossary_max_tokens: int = field(default_factory=lambda: int(_env("GLOSSARY_MAX_TOKENS", "10000")))

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


settings = Settings()
