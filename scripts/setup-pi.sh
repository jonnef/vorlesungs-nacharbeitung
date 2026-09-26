#!/usr/bin/env bash
# Richtet die Web-App auf dem Raspberry Pi ein bzw. aktualisiert sie.
# Wird von install.sh (auf dem Mac) per SSH aufgerufen; kann auch direkt auf dem Pi laufen.
#
#   bash setup-pi.sh [env-datei]
#
# Die optionale env-Datei (wird danach gelöscht) kann ANTHROPIC_API_KEY und
# MONTHLY_BUDGET_USD enthalten. Vorhandene Werte in server/.env bleiben sonst erhalten.
set -euo pipefail

APP_DIR="$HOME/vorlesungs-nacharbeitung"
SERVER_DIR="$APP_DIR/server"
ENV_FILE="$SERVER_DIR/.env"

if [[ $# -ge 1 && -f "$1" ]]; then
  # shellcheck disable=SC1090
  source "$1"
  rm -f "$1"
fi

say() { printf '\033[1m[Pi]\033[0m %s\n' "$*"; }

cd "$SERVER_DIR"

if ! python3 -c "import venv, ensurepip" 2>/dev/null; then
  say "Installiere python3-venv …"
  sudo apt-get update -qq
  sudo apt-get install -y -qq python3-venv
fi

if [[ ! -x .venv/bin/python ]]; then
  say "Lege Python-Umgebung an …"
  python3 -m venv .venv
fi
say "Installiere Abhängigkeiten (dauert beim ersten Mal ein paar Minuten) …"
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r requirements.txt

# ---------- .env ----------
touch "$ENV_FILE"
chmod 600 "$ENV_FILE"

get_env() { grep -m1 "^$1=" "$ENV_FILE" | cut -d= -f2- || true; }
set_env() {
  grep -v "^$1=" "$ENV_FILE" > "$ENV_FILE.tmp" || true
  printf '%s=%s\n' "$1" "$2" >> "$ENV_FILE.tmp"
  mv "$ENV_FILE.tmp" "$ENV_FILE"
  chmod 600 "$ENV_FILE"
}

if [[ -n "${ANTHROPIC_API_KEY:-}" ]]; then
  set_env ANTHROPIC_API_KEY "$ANTHROPIC_API_KEY"
fi
if [[ -z "$(get_env ANTHROPIC_API_KEY)" ]]; then
  echo "Fehler: Kein ANTHROPIC_API_KEY in $ENV_FILE." >&2
  exit 1
fi
if [[ -z "$(get_env API_TOKEN)" ]]; then
  set_env API_TOKEN "$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
fi
if [[ -n "${MONTHLY_BUDGET_USD:-}" ]]; then
  set_env MONTHLY_BUDGET_USD "$MONTHLY_BUDGET_USD"
fi

# ---------- systemd-Dienst ----------
say "Richte Dienst ein (startet automatisch mit dem Pi) …"
sudo tee /etc/systemd/system/vorlesung.service > /dev/null <<EOF
[Unit]
Description=Vorlesungs-Nacharbeitung (Web-App)
After=network-online.target
Wants=network-online.target

[Service]
User=$(id -un)
WorkingDirectory=$SERVER_DIR
ExecStart=$SERVER_DIR/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
Restart=on-failure

[Install]
WantedBy=multi-user.target
EOF
# Öffentliche Vorschau: zweite Instanz mit Beispieldaten in einem eigenen Datenverzeichnis,
# schreibgeschützt und nur lokal erreichbar (Caddy liefert sie unter /vorschau/vorlesungen/ aus).
sudo tee /etc/systemd/system/vorlesung-vorschau.service > /dev/null <<EOF
[Unit]
Description=Vorlesungs-Nacharbeitung (öffentliche Vorschau mit Beispieldaten)
After=network-online.target

[Service]
User=$(id -un)
WorkingDirectory=$SERVER_DIR
Environment=DEMO_MODE=1
Environment=DATA_DIR=$SERVER_DIR/data-vorschau
ExecStart=$SERVER_DIR/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8001
Restart=on-failure

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --quiet vorlesung vorlesung-vorschau
sudo systemctl restart vorlesung vorlesung-vorschau

wait_for() {  # wait_for <port> <name>
  for _ in $(seq 1 30); do
    code=$(curl -s -o /dev/null -w '%{http_code}' "http://localhost:$1/" || true)
    if [[ "$code" == "200" || "$code" == "401" ]]; then
      say "$2 läuft auf Port $1."
      return 0
    fi
    sleep 1
  done
  return 1
}
wait_for 8000 "Web-App" || { echo "Fehler: Web-App antwortet nicht. Log: journalctl -u vorlesung -n 50" >&2; exit 1; }
wait_for 8001 "Vorschau" || { echo "Fehler: Vorschau antwortet nicht. Log: journalctl -u vorlesung-vorschau -n 50" >&2; exit 1; }
