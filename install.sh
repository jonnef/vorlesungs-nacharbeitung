#!/usr/bin/env bash
# Einrichtung in einem Schritt – auf dem Mac im Terminal ausführen:
#
#   ./install.sh
#
# Richtet den Raspberry Pi per SSH ein (Web-App + Dienst) und danach den Mac
# (ffmpeg, Whisper-Modell, Hintergrund-Watcher). Erneut ausführen = aktualisieren.
set -euo pipefail

REPO="$(cd "$(dirname "$0")" && pwd)"
CONF_DIR="$HOME/.vorlesung-watcher"
CONF="$CONF_DIR/install.conf"
LABEL="de.vorlesung.watcher"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG="$HOME/Library/Logs/vorlesung-watcher.log"
ICLOUD="$HOME/Library/Mobile Documents/com~apple~CloudDocs"
WHISPER_MODEL="mlx-community/whisper-large-v3-turbo"

bold() { printf '\n\033[1m%s\033[0m\n' "$*"; }
die() { printf '\n\033[31mFehler:\033[0m %s\n' "$*" >&2; exit 1; }
ask() { # ask VAR "Frage" "Standard"
  local answer
  read -r -p "$2 [$3]: " answer
  printf -v "$1" '%s' "${answer:-$3}"
}

[[ "$(uname -s)" == "Darwin" ]] || die "Dieses Skript läuft auf dem Mac."
[[ "$(uname -m)" == "arm64" ]] || die "Für die lokale Transkription wird ein Mac mit Apple-Chip benötigt."

mkdir -p "$CONF_DIR"
# Antworten vom letzten Mal als Vorschlag
PI_HOST="raspberrypi.local"; PI_USER="pi"; BUDGET="10"; STUDIUM=""
# shellcheck disable=SC1090
[[ -f "$CONF" ]] && source "$CONF"

if [[ -z "$STUDIUM" ]]; then
  if [[ -d "$ICLOUD/Documents/Studium" ]]; then STUDIUM="$ICLOUD/Documents/Studium"
  elif [[ -d "$HOME/Documents/Studium" ]]; then STUDIUM="$HOME/Documents/Studium"
  else STUDIUM="$ICLOUD/Documents/Studium"; fi
fi

bold "Vorlesungs-Nacharbeitung – Einrichtung"
ask PI_HOST "Adresse des Raspberry Pi" "$PI_HOST"
ask PI_USER "Benutzername auf dem Pi" "$PI_USER"
ask BUDGET "Monatsbudget für Claude in USD" "$BUDGET"
ask STUDIUM "Studium-Ordner" "$STUDIUM"
STUDIUM="${STUDIUM/#\~/$HOME}"

cat > "$CONF" <<EOF
PI_HOST=$(printf %q "$PI_HOST")
PI_USER=$(printf %q "$PI_USER")
BUDGET=$(printf %q "$BUDGET")
STUDIUM=$(printf %q "$STUDIUM")
EOF

# ---------- Raspberry Pi ----------
bold "1/3 Raspberry Pi"
PI="$PI_USER@$PI_HOST"
# Eine SSH-Verbindung für alle Schritte → Passwort höchstens einmal eingeben.
SSH_OPTS=(-o ControlMaster=auto -o "ControlPath=$CONF_DIR/ssh-%C" -o ControlPersist=300 -o ConnectTimeout=10)
pi() { ssh "${SSH_OPTS[@]}" "$PI" "$@"; }

pi true || die "Keine SSH-Verbindung zu $PI. Ist der Pi an und SSH aktiviert?
(Raspberry Pi Imager → Einstellungen → Dienste → SSH aktivieren, oder auf dem Pi: sudo raspi-config → Interface Options → SSH)"

echo "Kopiere App auf den Pi …"
(cd "$REPO" && COPYFILE_DISABLE=1 tar --no-xattrs -czf - \
  --exclude .venv --exclude data --exclude .env --exclude __pycache__ --exclude .pytest_cache \
  server scripts) \
  | pi "mkdir -p ~/vorlesungs-nacharbeitung && tar -xzf - --warning=no-unknown-keyword -C ~/vorlesungs-nacharbeitung"

SETUP_ENV="$(printf 'MONTHLY_BUDGET_USD=%q\n' "$BUDGET")"
if ! pi "grep -q '^ANTHROPIC_API_KEY=.' ~/vorlesungs-nacharbeitung/server/.env 2>/dev/null"; then
  read -r -s -p "Claude-API-Key (sk-ant-…, Eingabe wird nicht angezeigt): " API_KEY; echo
  [[ "$API_KEY" == sk-ant-* ]] || die "Das sieht nicht nach einem API-Key aus."
  SETUP_ENV+=$'\n'"$(printf 'ANTHROPIC_API_KEY=%q' "$API_KEY")"
fi
# Key per stdin übertragen (nicht als Kommandozeilenargument sichtbar).
printf '%s\n' "$SETUP_ENV" | pi "umask 077; cat > ~/.vorlesung-setup.env"
ssh -t "${SSH_OPTS[@]}" "$PI" "bash ~/vorlesungs-nacharbeitung/scripts/setup-pi.sh ~/.vorlesung-setup.env"
TOKEN="$(pi "grep -m1 '^API_TOKEN=' ~/vorlesungs-nacharbeitung/server/.env | cut -d= -f2-")"
[[ -n "$TOKEN" ]] || die "API_TOKEN konnte nicht vom Pi gelesen werden."
SERVER="http://$PI_HOST:8000"

# ---------- Mac ----------
bold "2/3 Mac: Programme und Whisper-Modell"
if ! command -v brew >/dev/null; then
  if [[ -x /opt/homebrew/bin/brew ]]; then
    eval "$(/opt/homebrew/bin/brew shellenv)"
  else
    echo "Installiere Homebrew (fragt nach deinem Mac-Passwort) …"
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    eval "$(/opt/homebrew/bin/brew shellenv)"
  fi
fi
for pkg in ffmpeg python@3.12; do
  brew list --versions "$pkg" >/dev/null || brew install "$pkg"
done
PY="$(brew --prefix python@3.12)/bin/python3.12"

cd "$REPO/mac"
[[ -x .venv/bin/python ]] || "$PY" -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r requirements.txt
echo "Lade Whisper-Modell (einmalig ca. 1,6 GB) …"
.venv/bin/python -c "from huggingface_hub import snapshot_download; snapshot_download('$WHISPER_MODEL')" >/dev/null

# ---------- Ordner ----------
bold "3/3 Mac: Ordner und Hintergrund-Watcher"
mkdir -p "$STUDIUM/Vorlesungen"
MODULES=()
while IFS= read -r -d '' dir; do
  name="$(basename "$dir")"
  [[ "$name" == "Vorlesungen" || "$name" == .* ]] || MODULES+=("$name")
done < <(find "$STUDIUM" -mindepth 1 -maxdepth 1 -type d -print0 | sort -z)
if (( ${#MODULES[@]} )); then
  echo "Gefundene Modulordner: ${MODULES[*]}"
  ask CREATE "Dafür Videoordner unter Vorlesungen/ anlegen? (j/n)" "j"
  if [[ "$CREATE" == [jJyY]* ]]; then
    for m in "${MODULES[@]}"; do mkdir -p "$STUDIUM/Vorlesungen/$m"; done
  fi
fi

# ---------- LaunchAgent ----------
mkdir -p "$(dirname "$PLIST")" "$(dirname "$LOG")"
P_LABEL="$LABEL" P_REPO="$REPO" P_SERVER="$SERVER" P_TOKEN="$TOKEN" P_STUDIUM="$STUDIUM" P_LOG="$LOG" \
  .venv/bin/python - "$PLIST" <<'EOF'
import os, plistlib, sys
e = os.environ
plist = {
    "Label": e["P_LABEL"],
    "ProgramArguments": [e["P_REPO"] + "/mac/.venv/bin/python", e["P_REPO"] + "/mac/watcher.py"],
    "EnvironmentVariables": {
        "VORLESUNG_SERVER": e["P_SERVER"],
        "VORLESUNG_TOKEN": e["P_TOKEN"],
        "VORLESUNG_STUDIUM": e["P_STUDIUM"],
        "PATH": "/opt/homebrew/bin:/usr/bin:/bin",
    },
    "RunAtLoad": True,
    "KeepAlive": True,
    "ProcessType": "Background",
    "StandardOutPath": e["P_LOG"],
    "StandardErrorPath": e["P_LOG"],
}
with open(sys.argv[1], "wb") as f:
    plistlib.dump(plist, f)
EOF
chmod 600 "$PLIST"
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
: > "$LOG"
launchctl bootstrap "gui/$(id -u)" "$PLIST"

echo "Prüfe Zugriff auf iCloud Drive …"
sleep 8
if grep -q "Operation not permitted\|Kein Zugriff" "$LOG"; then
  REAL_PY="$(.venv/bin/python -c 'import os, sys; print(os.path.realpath(sys.executable))')"
  bold "Ein Klick fehlt noch: Festplattenvollzugriff für Python"
  echo "macOS lässt Hintergrundprogramme erst nach Freigabe auf iCloud Drive zugreifen."
  echo "Es öffnen sich gleich die Systemeinstellungen und ein Finder-Fenster:"
  echo "Ziehe die markierte Datei „$(basename "$REAL_PY")“ in die Liste und schalte sie ein."
  open "x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles"
  open -R "$REAL_PY"
  read -r -p "Enter drücken, wenn erledigt … "
  launchctl kickstart -k "gui/$(id -u)/$LABEL"
  sleep 8
  grep -q "Operation not permitted\|Kein Zugriff" "$LOG" && die "Immer noch kein Zugriff – Log: $LOG"
fi
grep -q "Pi nicht erreichbar" "$LOG" && echo "Warnung: Der Mac erreicht $SERVER nicht. Log: $LOG"

bold "Fertig!"
cat <<EOF
Weboberfläche:  $SERVER
Videos ablegen: $STUDIUM/Vorlesungen/<Modul>/
Dozenten-PDFs:  $STUDIUM/<Modul>/Skripte/
Notizen landen: $STUDIUM/<Modul>/Notizen/
Log:            $LOG

Updates später: im Repo 'git pull' und ./install.sh erneut ausführen.
EOF
