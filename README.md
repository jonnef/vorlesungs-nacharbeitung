# Vorlesungs-Nacharbeitung

Legt man ein Vorlesungsvideo in einen iCloud-Ordner, entsteht daraus automatisch ein
Transkript mit Zeitstempeln und daraus Lernnotizen nach Themen. Jede Aussage in den
Notizen ist mit dem Video-Zeitstempel `[hh:mm:ss]` und – wenn vorhanden – der
Skriptseite `[Kürzel S. 12]` belegt.

```
iCloud Drive/Vorlesungen/<Modul>/Videos/VL03.mp4
        │  MacBook (M4): mlx-whisper large-v3-turbo, lokal & kostenlos
        ▼
Raspberry Pi 5: Web-App ── passende Skriptseiten + Transkript ──▶ Claude (Opus 5, Batch-API)
        │                                                       Kosten vorab gezählt,
        ▼                                                       Monatsbudget als harte Grenze
iCloud Drive/Vorlesungen/<Modul>/Notizen/VL03.md   +   Weboberfläche http://raspberrypi.local:8000
```

| Ordner | Inhalt |
|---|---|
| `server/` | Web-App für den Pi (FastAPI + SQLite): Module, Skript-Upload, Claude-Jobs, Notizen, Kosten |
| `mac/` | Watcher für den Mac: iCloud-Ordner beobachten, transkribieren, Notizen zurückschreiben |

## 1. Claude API mit Kostenbremse einrichten

1. In der [Claude Console](https://console.anthropic.com) unter **Billing** Guthaben
   aufladen (Prepaid) und **Auto-Reload ausschalten**. Mehr als das Guthaben kann dann nie
   abgebucht werden.
2. Unter **Workspaces** einen eigenen Workspace „Vorlesungen“ anlegen und dort ein
   **Spend Limit** pro Monat setzen (z. B. 10 $).
3. In diesem Workspace einen API-Key erzeugen. Er kommt nur auf den Pi.

Zusätzlich kontrolliert die App die Kosten selbst:

- Vor jedem Job zählt sie die Tokens exakt (`count_tokens`) und berechnet die
  **Höchstkosten** (alle Input-Tokens + voll ausgeschöpfter Antwortdeckel).
- Ein Job startet nur, wenn diese Höchstkosten noch ins Monatsbudget passen
  (`MONTHLY_BUDGET_USD`, abzüglich schon ausgegebener und für laufende Jobs reservierter Beträge).
  Sonst bleibt er im Status „Budget reicht nicht“.
- Abgerechnet wird über die **Batch-API** (−50 %). Die tatsächlichen Kosten liest die App aus
  `usage` jeder Antwort und zeigt sie unter „Kosten“.
- Es werden nur die zur Vorlesung passenden Skriptseiten mitgeschickt
  (`SCRIPT_CONTEXT_TOKENS`, Standard 60 000).
- Mit `AUTO_SUBMIT=0` muss jeder Job per Klick freigegeben werden.

**Richtwert:** Eine 90-minütige Vorlesung kostet mit Opus 5 im Batch etwa **0,20–0,40 $**
(ca. 50–85 k Input-Tokens, 8–15 k Output-Tokens inkl. Denkprozess). Die Obergrenze pro Job
liegt bei den Standardeinstellungen um 0,45 $.

## 2. Raspberry Pi (Web-App)

```bash
git clone <dieses Repo> ~/vorlesungs-nacharbeitung
cd ~/vorlesungs-nacharbeitung/server
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env    # ANTHROPIC_API_KEY, API_TOKEN, Budget eintragen
.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000   # Test: http://raspberrypi.local:8000
```

Dauerhaft als Dienst (startet mit dem Pi): Benutzer und Pfade in `vorlesung.service` prüfen, dann

```bash
sudo cp vorlesung.service /etc/systemd/system/
sudo systemctl enable --now vorlesung
journalctl -u vorlesung -f   # Log
```

Daten liegen in `server/data/` (SQLite + hochgeladene PDFs). Für Backups reicht dieser Ordner.
Die Weboberfläche ist für das Heimnetz gedacht. Mit `WEB_PASSWORD` fragt sie ein Passwort ab.

## 3. MacBook (Watcher)

```bash
brew install ffmpeg python@3.12
git clone <dieses Repo> ~/vorlesungs-nacharbeitung
cd ~/vorlesungs-nacharbeitung/mac
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt
# Einmal manuell testen (lädt beim ersten Mal das Whisper-Modell, ~1,6 GB):
VORLESUNG_SERVER=http://raspberrypi.local:8000 VORLESUNG_TOKEN=<API_TOKEN vom Pi> \
  .venv/bin/python watcher.py --once
```

Automatisch im Hintergrund: in `de.vorlesung.watcher.plist` `DEIN_NAME`, Server und Token
eintragen, dann

```bash
cp de.vorlesung.watcher.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/de.vorlesung.watcher.plist
tail -f ~/Library/Logs/vorlesung-watcher.log
```

macOS erlaubt Hintergrundprozessen den Zugriff auf iCloud Drive evtl. erst nach Freigabe:
**Systemeinstellungen → Datenschutz & Sicherheit → Festplattenvollzugriff** →
`~/vorlesungs-nacharbeitung/mac/.venv/bin/python` (bzw. die Python-Datei, auf die es zeigt) hinzufügen.

Transkribiert wird nur, während der Mac wach ist. Eine 90-minütige Vorlesung dauert auf
einem M4 mit `large-v3-turbo` grob 5–10 Minuten.

## Benutzung

1. Modul anlegen: einfach einen Ordner `iCloud Drive/Vorlesungen/<Modulname>/` erstellen.
   Der Watcher legt darin `Skripte/` und `Videos/` an.
2. PDFs des Dozenten in `Skripte/` legen (oder in der Weboberfläche hochladen).
   Jedes Skript bekommt ein Kürzel, das in den Seitenangaben erscheint.
3. Heruntergeladene Videos (Moodle/Panopto …) in `Videos/` legen. Ein gut lesbarer Dateiname
   wird zum Titel, z. B. `VL03 Eigenwerte.mp4`.
4. Der Watcher transkribiert (Ergebnis zusätzlich in `Transkripte/`), schickt das Transkript
   an den Pi, der Pi startet den Claude-Job. Nach meist unter einer Stunde liegen die
   Notizen in `Notizen/` und in der Weboberfläche.

In der Weboberfläche sieht man pro Vorlesung Status, Höchstkosten, Notizen, das komplette
Transkript und Warnungen, falls Claude eine Seite oder einen Zeitstempel zitiert, den es
nicht gibt. Werden später weitere Skripte hochgeladen, erzeugt „Neu erstellen“ die Notizen
mit dem neuen Material erneut (die aktualisierte Fassung gibt es dann in der Weboberfläche).

## Entwicklung

```bash
cd server
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest
```

Die Tests ersetzen den Claude-Client durch eine Attrappe und kosten nichts.

## Einstellungen (`server/.env`)

| Variable | Standard | Bedeutung |
|---|---|---|
| `CLAUDE_MODEL` | `claude-opus-5` | Modell für die Notizen |
| `CLAUDE_EFFORT` | `high` | Denkaufwand (`low` … `max`), beeinflusst Qualität und Kosten |
| `MAX_OUTPUT_TOKENS` | `20000` | Deckel für Antwort + Denkprozess |
| `SCRIPT_CONTEXT_TOKENS` | `60000` | max. Tokens an Skriptseiten pro Vorlesung |
| `MONTHLY_BUDGET_USD` | `10` | harte Monatsgrenze in der App |
| `AUTO_SUBMIT` | `1` | `0` = jeden Job manuell freigeben |
| `API_TOKEN` | – | gemeinsamer Schlüssel für den Mac-Watcher |
| `WEB_PASSWORD` | – | optionales Passwort für die Weboberfläche |
