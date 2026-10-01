# Datenschutz

Alle Dateien werden vollständig lokal auf dem PC verarbeitet; es wird nichts hochgeladen. Die einzige
Verbindung ins Internet ist die Update-Prüfung (siehe unten). PDF Tool schreibt Einstellungen, die Kundenakten
(`kundenakten.json`), die Vertragsstände (`contract-history\`), den aktuellen Stapel (`stapel.json`)
und die technischen Protokolle `pdf-repair.log` und `stapel.log` in den Datenordner. Auch die
Stapelverarbeitung, der Vertragsvergleich und die erweiterte PDF-Wiederherstellung arbeiten
vollständig lokal – keine Cloud, keine Uploads.

**Vertragsstände** enthalten nur, was ohnehin in der erstellten Übersicht steht, und bleiben auf
diesem PC. Protokolle enthalten weder Vertragsdaten noch Verläufe von Kunden; Fehler beim Speichern
eines Stands werden ohne Vertragsinhalte protokolliert. Wer die Benutzerdaten sichert, sichert den
Ordner `%APPDATA%\PDF-Tool` vollständig – `contract-history` gehört dazu – oder nutzt die eingebaute
Sicherung (siehe unten).

**Die Kundenakte ist optional** (Standard: aus). Ist sie ausgeschaltet, werden keine Kundendaten
automatisch gespeichert oder abgeglichen, und `kundenakten.json` wird nicht gelesen; vorhandene
Kundendaten bleiben unverändert erhalten.

**Kundenakten und E-Mail-Zuordnungen** sind ausschließlich lokal gespeicherte Nutzerdaten: keine
Cloud, keine Telemetrie, keine Synchronisierung, keine E-Mail-Abfrage, keine Internetsuche und
keine Domain-Auflösung. Gespeichert werden nur Angaben, die der Benutzer bewusst speichert, sowie
Pfade der zuletzt verwendeten Excel- und PDF-Datei – keine Kopien der Dateien. Löschen entfernt
die Kundenakte und ihre Zuordnungen, nie PDF- oder Excel-Dateien. Das Protokoll enthält Dateinamen, Größen und technische
Befunde, aber keine PDF-Inhalte, keine vollständigen Pfade und keine Passwörter. Zwischendateien
entstehen nur im temporären Ordner von Windows und werden nach jedem Vorgang gelöscht.

**Updates (seit 2.7.2):** PDF Tool fragt die Releases des offiziellen Repositories bei GitHub ab –
automatisch höchstens einmal täglich (abschaltbar unter Einstellungen → Updates) oder mit „Nach
Updates suchen“. Dabei werden keine Dateien, keine Einstellungen und keine persönlichen Daten
übertragen; GitHub erhält wie bei jedem Webseitenaufruf die IP-Adresse und die Kennung
„PDF-Tool/<Version>“. Heruntergeladen wird nur auf Klick; Setups liegen in
`%LOCALAPPDATA%\PDF-Tool-Updates` und werden nach einem Update aufgeräumt bzw. bei der
Deinstallation entfernt.

**Sicherungen (seit 2.8):** Eine Sicherung (`.pdtbackup`) enthält Einstellungen, Kundenakten mit
Vertragsständen, Vorlagen und Regelwerke dieses PCs – nie Excel- oder PDF-Dateien, Logos oder
Protokolle. Sie bleibt lokal: automatisch im Ordner `%APPDATA%\PDF-Tool\Sicherungen` (wählbar),
manuell dort, wo Sie sie ablegen. Keine Cloud, keine Uploads. Eine Sicherung enthält
personenbezogene Daten der Kundenakten – bitte entsprechend aufbewahren. Der Status der
Sicherungen steht in `sicherung.json` im Datenordner.

**Diagnose und Support-Paket (seit 2.8):** Die Datenprüfung liest nur und ändert nichts. Das
Support-Paket entsteht nur auf Klick, bleibt auf diesem PC und wird nie versendet. Es enthält einen
Bericht (Versionen, Windows, Ergebnis der Prüfung), Einstellungen ohne persönliche Inhalte und
bereinigte Protokolle: Pfade zu Dokumenten, der Benutzerordner, Benutzer- und Computername,
E-Mail-Adressen sowie Firmen und Kundennummern der Kundenakten sind entfernt. Nie enthalten:
Kundendaten, Vertragsinhalte, Texte von Vorlagen, Regelwerken, Kopf- und Fußzeilen, Passwörter,
PDF- oder Excel-Dateien und deren Inhalte, Logos. Das Protokoll `pdf-tool.log` enthält Abläufe
(Start, Sicherung, Updates, Fehler), keine Inhalte.
