#!/usr/bin/env bash
# Aktualisiert die Web-App auf dem Pi aus einem Git-Klon (läuft auf dem Pi).
# Wird von update-pi-windows.bat per SSH aufgerufen; geht auch direkt auf dem Pi:
#
#   bash ~/vorlesungs-nacharbeitung-src/scripts/update-pi.sh
#
# Kopiert server/ und scripts/ aus dem Klon nach ~/vorlesungs-nacharbeitung – ohne Daten,
# Einstellungen (.env) und Python-Umgebung – und startet dann setup-pi.sh.
set -euo pipefail

SRC="$(cd "$(dirname "$0")/.." && pwd)"
APP_DIR="$HOME/vorlesungs-nacharbeitung"

if [[ "$SRC" == "$APP_DIR" ]]; then
  echo "Fehler: Bitte aus dem Git-Klon starten, nicht aus $APP_DIR." >&2
  exit 1
fi

printf '\033[1m[Pi]\033[0m Übernehme Stand %s …\n' "$(git -C "$SRC" log -1 --format='%h %s' 2>/dev/null || echo '?')"
mkdir -p "$APP_DIR"
# Wie install.sh: per tar, damit nur vorhandene Dateien überschrieben werden.
(cd "$SRC" && tar -czf - --exclude server/data --exclude server/data-vorschau --exclude server/.env \
  --exclude server/.venv --exclude __pycache__ --exclude .pytest_cache server scripts) \
  | tar -xzf - -C "$APP_DIR"

bash "$APP_DIR/scripts/setup-pi.sh"
