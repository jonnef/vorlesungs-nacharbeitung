#!/usr/bin/env bash
# Aktualisiert die Web-App auf dem Raspberry Pi vom Mac aus (Doppelklick im Finder genügt)
# und bietet an, das automatische Deployment (GitHub-Actions-Runner) einzurichten.
# Gegenstück zu update-pi-windows.bat. Daten und Einstellungen (.env) auf dem Pi bleiben.
set -uo pipefail

REPO_URL="https://github.com/jonnef/vorlesungs-nacharbeitung.git"
CONF="$HOME/.vorlesung-watcher/install.conf"   # Antworten aus install.sh als Vorschlag
PI_HOST="raspberrypi.local"; PI_USER="pi"
# shellcheck disable=SC1090
[[ -f "$CONF" ]] && source "$CONF"

printf '\n\033[1mVorlesungs-Nacharbeitung: Pi aktualisieren\033[0m\n\n'
read -r -p "Pi-Benutzer@Adresse [$PI_USER@$PI_HOST]: " PI
PI="${PI:-$PI_USER@$PI_HOST}"
read -r -p "Branch [main]: " BRANCH
BRANCH="${BRANCH:-main}"

echo
echo "Verbinde mit $PI (ggf. erst das Pi-Passwort eingeben) …"
ssh -t "$PI" "set -e; if ! command -v git >/dev/null; then sudo apt-get update -qq && sudo apt-get install -y -qq git; fi
if [ -d ~/vorlesungs-nacharbeitung-src/.git ]; then git -C ~/vorlesungs-nacharbeitung-src fetch -q origin; else git clone -q $REPO_URL ~/vorlesungs-nacharbeitung-src; fi
git -C ~/vorlesungs-nacharbeitung-src checkout -q -B $BRANCH origin/$BRANCH
bash ~/vorlesungs-nacharbeitung-src/scripts/update-pi.sh"
rc=$?
echo
if (( rc != 0 )); then
  echo "Das Update ist fehlgeschlagen – siehe Meldungen oben."
  read -r -p "Enter zum Schließen … "
  exit 1
fi
echo "Fertig."

if ssh "$PI" "test -f ~/actions-runner-vorlesungen/.runner"; then
  echo "Automatisches Deployment ist schon eingerichtet – künftig reicht ein Merge auf main."
else
  echo
  echo "Automatisches Deployment: Nach jedem Merge auf main aktualisiert sich der Pi selbst."
  echo "Dafür einmalig einen Token von GitHub holen: Repository → Settings → Actions → Runners →"
  echo "„New self-hosted runner“ (Linux, ARM64) – der Wert hinter --token, gilt eine Stunde."
  read -r -p "Jetzt einrichten? (j/N): " RUNNER
  if [[ "$RUNNER" == [jJyY]* ]]; then
    ssh -t "$PI" "bash ~/vorlesungs-nacharbeitung-src/scripts/install-runner.sh"
  fi
fi
echo
read -r -p "Enter zum Schließen … "
