# Übersichten-Ersteller

Quellcode für den **Übersichten-Ersteller 2.0.5**.

Das Repository enthält:

- die Windows-App unter `windows-app/`
- den Go-basierten Windows-Installer unter `windows-app/installer/`
- die Web-/Downloadseite auf Basis von React, TanStack Start und Vite

## Windows-App

Die Anwendung erstellt Vertragsübersichten aus Excel-Daten und exportiert diese als PDF. Der Build-Prozess für die Windows-Version liegt in `windows-app/pack.py`.

## Sicherheit

Lokale Build-Artefakte, Grok-Workspace-Metadaten, Screenshots, Caches und vorkompilierte EXE-/ZIP-Dateien werden nicht versioniert. OAuth-Secrets gehören ausschließlich in Umgebungsvariablen und sind nicht im Repository enthalten.
