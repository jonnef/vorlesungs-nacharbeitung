#!/usr/bin/env bash
# Richtet auf dem Pi einen GitHub-Actions-Runner für dieses Repository ein (einmalig).
# Danach wird jeder Merge auf main automatisch auf den Pi deployt (.github/workflows/ci-deploy.yml).
#
#   bash ~/vorlesungs-nacharbeitung-src/scripts/install-runner.sh
#
# Den Token gibt es auf GitHub: Repository → Settings → Actions → Runners → „New self-hosted
# runner“ (steht dort in der Zeile mit ./config.sh … --token XXXX; gilt eine Stunde).
# Der Runner liegt in einem eigenen Ordner und stört andere Runner auf dem Pi nicht.
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/jonnef/vorlesungs-nacharbeitung}"
DIR="$HOME/actions-runner-vorlesungen"

say() { printf '\033[1m[Pi]\033[0m %s\n' "$*"; }

if [[ -f "$DIR/.runner" ]]; then
  say "Der Runner ist schon eingerichtet ($DIR). Status: sudo $DIR/svc.sh status"
  exit 0
fi

case "$(uname -m)" in
  aarch64|arm64) ARCH=arm64 ;;
  armv7l|armv6l) ARCH=arm ;;
  x86_64) ARCH=x64 ;;
  *) echo "Fehler: Unbekannte Architektur $(uname -m)." >&2; exit 1 ;;
esac

if ! sudo -n true 2>/dev/null; then
  echo "Hinweis: Das Deployment braucht sudo ohne Passwort (für systemctl/apt in setup-pi.sh)." >&2
  echo "Auf Raspberry Pi OS ist das für den Standardbenutzer üblich; sonst einen sudoers-Eintrag anlegen." >&2
fi

VERSION="$(curl -fsSL https://api.github.com/repos/actions/runner/releases/latest \
  | python3 -c 'import json, sys; print(json.load(sys.stdin)["tag_name"].lstrip("v"))')"
say "Lade GitHub-Actions-Runner $VERSION ($ARCH) …"
mkdir -p "$DIR"
cd "$DIR"
curl -fsSL -o runner.tgz \
  "https://github.com/actions/runner/releases/download/v$VERSION/actions-runner-linux-$ARCH-$VERSION.tar.gz"
tar -xzf runner.tgz
rm runner.tgz
sudo ./bin/installdependencies.sh >/dev/null

read -r -s -p "Runner-Token von GitHub (Eingabe wird nicht angezeigt): " TOKEN
echo
./config.sh --url "$REPO_URL" --token "$TOKEN" --name "$(hostname)-vorlesungen" \
  --labels pi --unattended --replace
sudo ./svc.sh install "$(id -un)"
sudo ./svc.sh start
say "Runner läuft. Ab jetzt wird jeder Merge auf main automatisch deployt."
