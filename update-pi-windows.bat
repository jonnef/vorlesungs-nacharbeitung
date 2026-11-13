@echo off
rem Aktualisiert die Web-App auf dem Raspberry Pi von Windows aus (Doppelklick genuegt).
rem Braucht nur das in Windows 10/11 eingebaute SSH. Auf dem Pi wird das Repository nach
rem ~/vorlesungs-nacharbeitung-src geklont bzw. aktualisiert und dann scripts/update-pi.sh
rem gestartet. Daten und Einstellungen (.env) auf dem Pi bleiben erhalten.
chcp 65001 >nul
setlocal

set "PI=pi@raspberrypi.local"
set "BRANCH=main"
set "REPO=https://github.com/jonnef/vorlesungs-nacharbeitung.git"

echo.
echo  Vorlesungs-Nacharbeitung: Pi aktualisieren
echo  ------------------------------------------
echo.

where ssh >nul 2>nul
if errorlevel 1 (
  echo Fehler: SSH fehlt. Windows-Einstellungen ^> System ^> Optionale Features ^> "OpenSSH-Client" hinzufuegen.
  pause
  exit /b 1
)

set "INPUT="
set /p "INPUT=Pi-Benutzer@Adresse [%PI%]: "
if not "%INPUT%"=="" set "PI=%INPUT%"
set "INPUT="
set /p "INPUT=Branch [%BRANCH%]: "
if not "%INPUT%"=="" set "BRANCH=%INPUT%"

echo.
echo Verbinde mit %PI% (ggf. erst das Pi-Passwort eingeben) ...
echo.
ssh -t %PI% "set -e; if ! command -v git >/dev/null; then sudo apt-get update -qq && sudo apt-get install -y -qq git; fi; if [ -d ~/vorlesungs-nacharbeitung-src/.git ]; then git -C ~/vorlesungs-nacharbeitung-src fetch -q origin; else git clone -q %REPO% ~/vorlesungs-nacharbeitung-src; fi; git -C ~/vorlesungs-nacharbeitung-src checkout -q -B %BRANCH% origin/%BRANCH%; bash ~/vorlesungs-nacharbeitung-src/scripts/update-pi.sh"
set "RC=%ERRORLEVEL%"

echo.
if not "%RC%"=="0" (
  echo Das Update ist fehlgeschlagen - siehe Meldungen oben.
  echo.
  pause
  exit /b 1
)
echo Fertig. Weboberflaeche: http://raspberrypi.local:8000
echo.

rem Einmalig: Runner fuer automatisches Deployment nach jedem Merge auf main einrichten.
echo Automatisches Deployment: Nach jedem Merge auf main aktualisiert sich der Pi selbst.
echo Dafuer braucht es einmalig einen Token von GitHub: Repository - Settings - Actions -
echo Runners - "New self-hosted runner" (Wert hinter --token, gilt eine Stunde).
set "RUNNER="
set /p "RUNNER=Jetzt einrichten? (j/N): "
if /i not "%RUNNER%"=="j" goto ende
ssh -t %PI% "bash ~/vorlesungs-nacharbeitung-src/scripts/install-runner.sh"

:ende
echo.
pause
