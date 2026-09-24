# Vorlesungs-Nacharbeitung – Planung

## Ziel
- Modul anlegen, Dozenten-Dateien (Skripte, PDFs) als Kontext hochladen
- Vorlesungsvideos in einen Ordner legen → automatisches Transkript (mit Zeitstempeln)
- Wichtigste Inhalte nach Themen zusammenfassen, verknüpft mit Skriptseiten [S. x] und Video-Zeitstempeln [hh:mm:ss]

## Architektur (Vorschlag)
- **MacBook Air (Apple Silicon)**: Hintergrund-Dienst beobachtet `iCloud/Vorlesungen/<Modul>/Videos`,
  extrahiert Audio (ffmpeg), transkribiert lokal mit Whisper `large-v3-turbo` (MLX/Metal),
  schickt Transkript an den Pi, legt fertige Notizen (Markdown) zurück in iCloud.
- **Raspberry Pi**: Web-App (Python) – Module, Skript-Upload (seitenweise Textextraktion),
  Claude-Jobs, Notizen-Ansicht, Kosten/Budget.
- iCloud nicht direkt auf dem Pi (kein offizieller Linux-Client; rclone fragil) → Mac ist die Brücke.

## Kostenkontrolle (Claude API)
- Prepaid-Guthaben, Auto-Reload aus (harte Grenze)
- Eigener Workspace + Spend-Limit + eigener API-Key
- In der App: Token-Zählung vor jedem Job, Kostenschätzung, Monatsbudget blockiert, Logging aus `usage`
- Nur relevante Skriptseiten senden; Batch-API (−50 %); `max_tokens`-Deckel
- Schätzung pro Vorlesung (Batch): Opus 5 ~0,28 $, Sonnet 5 ~0,11 $

## Entscheidungen
1. Hardware: MacBook Air M4 (16 GB), Raspberry Pi 5
2. Modell: immer Opus (`claude-opus-5`, über `CLAUDE_MODEL` änderbar)
3. Kein Video-Player – nur Text-Zeitstempel
4. Videos werden manuell heruntergeladen und in den iCloud-Ordner gelegt

Umsetzung und Einrichtung: siehe README.md.
