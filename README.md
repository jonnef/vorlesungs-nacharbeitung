# Vorlesungs-Nacharbeitung

Legt man ein Vorlesungsvideo in einen iCloud-Ordner, entsteht daraus automatisch ein
Transkript mit Zeitstempeln und daraus Lernnotizen nach Themen. Jede Aussage in den
Notizen ist mit dem Video-Zeitstempel `[hh:mm:ss]` und – wenn vorhanden – der
Skriptseite `[Kürzel S. 12]` belegt.

```
iCloud Drive/Dokumente/Studium/Vorlesungen/<Modul>/VL03.mp4
        │  MacBook (M4): mlx-whisper large-v3-turbo, lokal & kostenlos
        ▼
Raspberry Pi 5: Web-App ── passende Skriptseiten + Transkript ──▶ Claude (Opus 5, Batch-API)
        │                                                       Kosten vorab gezählt,
        ▼                                                       Monatsbudget als harte Grenze
iCloud Drive/Dokumente/Studium/<Modul>/Notizen/VL03.md   +   Weboberfläche http://raspberrypi.local:8000
```

| Ordner | Inhalt |
|---|---|
| `server/` | Web-App für den Pi (FastAPI + SQLite): Module, Skript-Upload, Claude-Jobs, Notizen, Kosten |
| `mac/` | Watcher für den Mac: iCloud-Ordner beobachten, transkribieren, Notizen zurückschreiben |
| `install.sh` | Einrichtung von Pi und Mac in einem Schritt (läuft auf dem Mac) |
| `scripts/setup-pi.sh` | Pi-Teil der Einrichtung (wird von `install.sh` per SSH aufgerufen) |

## 1. Claude API mit Kostenbremse einrichten

1. In der [Claude Console](https://console.anthropic.com) unter **Billing** Guthaben
   aufladen (Prepaid) und **Auto-Reload ausschalten**. Mehr als das Guthaben kann dann nie
   abgebucht werden.
2. Unter **Workspaces** einen eigenen Workspace „Vorlesungen“ anlegen und dort ein
   **Spend Limit** pro Monat setzen (z. B. 10 $).
3. In diesem Workspace einen API-Key erzeugen. `install.sh` legt ihn nur auf dem Pi ab.

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

## 2. Installation (ein Befehl, auf dem Mac)

Voraussetzungen: Der Pi läuft mit Raspberry Pi OS, ist im selben Netz und hat SSH aktiviert
(im Raspberry Pi Imager unter „Dienste“ oder auf dem Pi mit `sudo raspi-config` →
Interface Options → SSH). Den Claude-API-Key aus Schritt 1 bereithalten.

Im Terminal auf dem Mac:

```bash
git clone https://github.com/jonnef/vorlesungs-nacharbeitung.git ~/vorlesungs-nacharbeitung
~/vorlesungs-nacharbeitung/install.sh
```

Ist das Repository privat und `git clone` fragt nach Zugangsdaten, geht auch: auf GitHub
„Code → Download ZIP“, entpacken nach `~/vorlesungs-nacharbeitung` und dann `install.sh` starten.

Das Skript fragt nach Pi-Adresse, Pi-Benutzer, Monatsbudget und API-Key und erledigt dann alles:

- **Pi:** kopiert die App per SSH, installiert sie, erzeugt das API-Token, trägt Key und Budget
  in `server/.env` ein und richtet den Dienst ein, der mit dem Pi startet.
- **Mac:** installiert Homebrew (falls nötig), ffmpeg, Python und mlx-whisper, lädt das
  Whisper-Modell (~1,6 GB), legt `Studium/Vorlesungen/` an (auf Wunsch mit einem Ordner pro
  vorhandenem Modul) und startet den Watcher als Hintergrunddienst.
- Falls macOS den Zugriff auf iCloud Drive blockiert, öffnet es die Systemeinstellungen an der
  richtigen Stelle. Dann musst du Python einmal den Festplattenvollzugriff geben.

Aktualisieren: `cd ~/vorlesungs-nacharbeitung && git pull && ./install.sh`. Die vorigen Antworten
werden vorgeschlagen, den API-Key fragt es nicht erneut ab.

Nützliches danach:

| | |
|---|---|
| Weboberfläche | `http://raspberrypi.local:8000` |
| Log Mac | `tail -f ~/Library/Logs/vorlesung-watcher.log` |
| Log Pi | `ssh pi@raspberrypi.local journalctl -u vorlesung -f` |
| Daten Pi (Backup) | `~/vorlesungs-nacharbeitung/server/data/` |
| Einstellungen Pi | `~/vorlesungs-nacharbeitung/server/.env`, danach `sudo systemctl restart vorlesung` |

Transkribiert wird nur, während der Mac wach ist. Eine 90-minütige Vorlesung dauert auf
einem M4 mit `large-v3-turbo` grob 5–10 Minuten.

## Benutzung

Alles liegt in `iCloud Drive/Dokumente/Studium/`:

```
Studium/
  Vorlesungen/
    Analysis II/         ← heruntergeladene Videos hier hineinlegen
  Analysis II/           ← dein vorhandener Modulordner
    Skripte/             ← PDFs des Dozenten (auch Unterordner)
    Transkripte/         ← legt der Watcher an
    Notizen/             ← fertige Lernnotizen (Markdown)
```

1. PDFs des Dozenten in `Studium/<Modul>/Skripte/` legen. Jedes Skript bekommt ein Kürzel, das
   in den Seitenangaben erscheint. Andere Dateien im Modulordner werden nicht angefasst.
2. Heruntergeladene Videos (Moodle/Panopto …) in `Studium/Vorlesungen/<Modul>/` legen. Der
   Ordnername muss genauso heißen wie der Modulordner. Ein gut lesbarer Dateiname wird zum Titel,
   z. B. `VL03 Eigenwerte.mp4`.
3. Der Watcher transkribiert, schickt das Transkript an den Pi, der Pi startet den Claude-Job.
   Nach meist unter einer Stunde liegen die Notizen in `Studium/<Modul>/Notizen/` und in der
   Weboberfläche.

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
