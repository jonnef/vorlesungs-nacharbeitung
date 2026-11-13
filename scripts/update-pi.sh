#!/usr/bin/env bash
# Aktualisiert die Web-App auf dem Pi aus einem Git-Stand (läuft auf dem Pi).
#
# Aufrufer:
#   - GitHub Actions (Runner auf dem Pi) nach jedem Merge auf main – siehe .github/workflows/
#   - update-pi-windows.bat per SSH bzw. von Hand:
#       bash ~/vorlesungs-nacharbeitung-src/scripts/update-pi.sh
#
# Ablauf: Datenbank sichern → server/ und scripts/ übernehmen (ohne Daten, .env und
# Python-Umgebung) → setup-pi.sh (Abhängigkeiten, Dienst neu starten, prüft, ob die App
# antwortet). Schlägt das fehl, wird der vorige Stand zurückgespielt und neu gestartet.
set -euo pipefail

SRC="$(cd "$(dirname "$0")/.." && pwd)"
APP_DIR="$HOME/vorlesungs-nacharbeitung"
DB="$APP_DIR/server/data/app.db"
BACKUP_DIR="$APP_DIR/server/data/backups"
KEEP_BACKUPS=10
PREVIOUS="$HOME/.vorlesung-vorheriger-stand.tgz"

say() { printf '\033[1m[Pi]\033[0m %s\n' "$*"; }

if [[ "$SRC" == "$APP_DIR" ]]; then
  echo "Fehler: Bitte aus dem Git-Klon starten, nicht aus $APP_DIR." >&2
  exit 1
fi

pack() {  # pack <verzeichnis>: server/ und scripts/ ohne Daten, Einstellungen und venv
  (cd "$1" && tar -czf - --exclude server/data --exclude server/data-vorschau --exclude server/.env \
    --exclude server/.venv --exclude __pycache__ --exclude .pytest_cache server scripts)
}

say "Übernehme Stand $(git -C "$SRC" log -1 --format='%h %s' 2>/dev/null || echo '?') …"

# 1. Datenbank sichern (konsistente Kopie per SQLite-Backup, auch während die App läuft)
if [[ -f "$DB" ]]; then
  mkdir -p "$BACKUP_DIR"
  target="$BACKUP_DIR/app-$(date +%Y%m%d-%H%M%S).db"
  python3 -c 'import sqlite3, sys; s = sqlite3.connect(sys.argv[1]); d = sqlite3.connect(sys.argv[2]); s.backup(d); d.close(); s.close()' \
    "$DB" "$target"
  say "Datenbank gesichert: $target"
  # nur die neuesten Sicherungen behalten
  ls -1t "$BACKUP_DIR"/app-*.db 2>/dev/null | tail -n +$((KEEP_BACKUPS + 1)) | xargs -r rm -f
fi

# 2. Bisherigen Stand merken (für den Fall, dass der neue nicht startet)
if [[ -d "$APP_DIR/server" ]]; then
  pack "$APP_DIR" > "$PREVIOUS"
fi

# 3. Neuen Stand übernehmen und einrichten
mkdir -p "$APP_DIR"
pack "$SRC" | tar -xzf - -C "$APP_DIR"
if bash "$APP_DIR/scripts/setup-pi.sh"; then
  say "Update fertig."
  exit 0
fi

# 4. Fehlgeschlagen → vorigen Stand zurückspielen
echo "Fehler: Der neue Stand startet nicht – spiele den vorigen Stand zurück." >&2
if [[ -f "$PREVIOUS" ]]; then
  tar -xzf "$PREVIOUS" -C "$APP_DIR"
  bash "$APP_DIR/scripts/setup-pi.sh" || echo "Auch der vorige Stand startet nicht – bitte Log prüfen: journalctl -u vorlesung -n 50" >&2
fi
exit 1
