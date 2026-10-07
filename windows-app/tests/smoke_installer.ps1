# Prueft das fertige Setup auf einem Windows-Rechner ohne eigenes Python:
#   0. nur mit -Previous: Vorversion installieren und Benutzerdaten anlegen –
#      Uebersichten-Ersteller 2.2.0, PDF Tool 2.3.0 (mit Kundenverlauf samt formatierter
#      Fusszeile, Vorlagen, Textbausteinen und Regeln), PDF Tool 2.4.0 (Kundenakten mit
#      formatierter Fusszeile und Vorlage, formatierte Kopfzeile, Einstellungen von "PDF reparieren"),
#      PDF Tool 2.5.0 (wie 2.4.0, dazu Stapel-Einstellungen und ein gespeicherter Vertragsstand)
#      oder PDF Tool 2.6.0 und neuer, z. B. 2.6.1 (wie 2.5.0, dazu eine aktive Kundenakte und die
#      Fensterlage der Tk-Oberflaeche, die seit 2.7.0 nur noch gelesen wird). Die Vorversion wird
#      nach ihrer Versionsnummer eingeordnet (Vergleich als Version, nicht als Text).
#   1. still installieren (bzw. aktualisieren) und Installation pruefen:
#      Ordner, Verknuepfungen, genau ein Eintrag unter "Installierte Apps"; Qt-Oberflaeche
#      (PySide6, QML als Ressource), keine Reste der Tk-Oberflaeche (tkinter, Tcl/Tk, lose QML)
#   2. nur mit -Previous: 2.2.0 – alter Programmordner und alte Verknuepfungen entfernt,
#      Benutzerdaten mit Sicherung nach %APPDATA%\PDF-Tool uebernommen, alte Daten unveraendert;
#      2.3.0/2.4.0/2.5.0/2.6.0 – das Setup laesst die Benutzerdaten unangetastet
#   3. installierte Laufzeit pruefen (Module, Vertragsuebersicht, Kundenakte, Vorschau,
#      PDF-Reparatur, Programmstart)
#   4. echter Start wie ueber die Verknuepfung (pythonw.exe start.py). Die Kundenakte ist seit 2.6.1
#      optional und auch nach einem Update zunaechst aus – vorhandene Kundendaten bleiben unangetastet.
#      Nach einem Update von 2.3.0: Kundenverlauf bleibt unveraendert erhalten; nach dem Einschalten
#      der Kundenakte mit Sicherung zu Kundenakten uebernommen, Formatierung, Standard-Fusszeile,
#      Vorlagen und Textbausteine erhalten; von 2.4.0: Einstellungen, Kundenakten, Vorlagen, Rich Text
#      und Reparatur-Einstellungen unveraendert; von 2.5.0/2.6.0: zusaetzlich Stapel-Einstellungen
#      erhalten, Vertragsstand unveraendert und lesbar, kein kuenstlicher neuer Stand; von 2.6.0:
#      Kundenakte aus, Kundenakten unveraendert und fuer die App lesbar
#   4b. »Oeffnen mit« (seit 3.0.0): Eintrag fuer PDF-Dateien vorhanden, die Standard-App fuer .pdf
#      unveraendert; Start mit einer PDF, ein zweiter Start reicht seine PDF an die laufende App weiter
#   5. still deinstallieren (auch die Eintraege fuer »Oeffnen mit« sind danach entfernt)
#
# Aufruf:
#   pwsh -File windows-app\tests\smoke_installer.ps1 -Setup windows-app\dist\PDF-Tool-Setup-<Version>.exe
#   pwsh -File windows-app\tests\smoke_installer.ps1 -Setup ...\PDF-Tool-Setup-<Version>.exe -Previous ...\Uebersichten-Ersteller-Setup-2.2.0.exe
#   pwsh -File windows-app\tests\smoke_installer.ps1 -Setup ...\PDF-Tool-Setup-<Version>.exe -Previous ...\PDF-Tool-Setup-2.3.0.exe
#   pwsh -File windows-app\tests\smoke_installer.ps1 -Setup ...\PDF-Tool-Setup-<Version>.exe -Previous ...\PDF-Tool-Setup-2.4.0.exe
#   pwsh -File windows-app\tests\smoke_installer.ps1 -Setup ...\PDF-Tool-Setup-<Version>.exe -Previous ...\PDF-Tool-Setup-2.5.0.exe
#   pwsh -File windows-app\tests\smoke_installer.ps1 -Setup ...\PDF-Tool-Setup-<Version>.exe -Previous ...\PDF-Tool-Setup-2.6.0.exe
#   pwsh -File windows-app\tests\smoke_installer.ps1 -Setup ...\PDF-Tool-Setup-<Version>.exe -Previous ...\PDF-Tool-Setup-2.6.1.exe
#
# Der normale Workflow (windows-setup.yml) ruft das Skript zweimal auf: ohne -Previous (Clean
# Install) und mit dem Setup der unmittelbar vorherigen stabilen Version. Aeltere Vorversionen
# prueft nur der manuelle Workflow "Deep Compatibility Test" (deep-compatibility.yml).
#
# Der Update-Test (-Previous) braucht einen Rechner ohne vorhandene Installation und ohne
# Benutzerdaten der App. Ordner, die das Skript selbst angelegt hat, entfernt es am Ende wieder.

param(
    [Parameter(Mandatory = $true)][string]$Setup,
    [string]$Previous = ""
)

$ErrorActionPreference = "Stop"
$Setup = (Resolve-Path $Setup).Path
$target = Join-Path $env:LOCALAPPDATA "PDF-Tool"
$data = Join-Path $env:APPDATA "PDF-Tool"
$oldTarget = Join-Path $env:LOCALAPPDATA "Uebersichten-Ersteller"
$oldData = Join-Path $env:APPDATA "Uebersichten-Ersteller"
$updates = Join-Path $env:LOCALAPPDATA "PDF-Tool-Updates"
$temp = if ($env:RUNNER_TEMP) { $env:RUNNER_TEMP } else { $env:TEMP }
$appName = "PDF Tool"
$oldAppName = "$([char]0x00DC)bersichten-Ersteller"
$programs = [Environment]::GetFolderPath("Programs")
$desktop = [Environment]::GetFolderPath("Desktop")
$shortcut = Join-Path $programs "$appName.lnk"
$oldShortcut = Join-Path $programs "$oldAppName.lnk"
$uninstallRoot = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall"
$appKey = Join-Path $uninstallRoot "{59C40061-D5E5-446D-ACB4-E077D3C71E1A}_is1"
# »Oeffnen mit« (seit 3.0.0): eigene ProgID; die Standard-App fuer .pdf bleibt unveraendert
$progIdKey = "HKCU:\Software\Classes\PDFTool.Dokument"
$openWithKey = "HKCU:\Software\Classes\.pdf\OpenWithProgids"
function RegValue([string]$path, [string]$name) {
    if (-not (Test-Path $path)) { return "<keiner>" }
    $value = [string](Get-Item -LiteralPath $path).GetValue($name)
    if ([string]::IsNullOrEmpty($value)) { return "<keiner>" }
    return $value
}
function PdfDefault() {
    # Standard-App fuer .pdf: Standardwert von Classes\.pdf und die Wahl des Benutzers (UserChoice).
    # Ein Schluessel ohne Wert gilt wie kein Schluessel: »Oeffnen mit« legt .pdf\OpenWithProgids an.
    $classes = RegValue "HKCU:\Software\Classes\.pdf" ""
    $choice = RegValue "HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\FileExts\.pdf\UserChoice" "ProgId"
    return "$classes / $choice"
}
$pdfDefaultBefore = PdfDefault
$pdfKeyBefore = Test-Path "HKCU:\Software\Classes\.pdf"
$env:UE_DATA_DIR = $null
$env:UE_CONFIG_FILE = $null

# Sprachmodelle des KI-Assistenten (seit 3.2, nur auf Wunsch geladen): eigener Ordner, nicht im Datenordner
$ki = Join-Path $env:LOCALAPPDATA "PDF-Tool-KI"
$kiNew = -not (Test-Path $ki)

# Ordner, die vor dem Test nicht existierten, werden am Ende entfernt (nie vorhandene Benutzerdaten).
$created = @($target, $data, $oldTarget, $oldData, $updates, $ki) | Where-Object { -not (Test-Path $_) }

function Install([string]$file, [string]$name) {
    $log = Join-Path $temp "setup-$name.log"
    $run = Start-Process -FilePath $file -ArgumentList "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/LOG=`"$log`"" -Wait -PassThru
    if ($run.ExitCode -ne 0) { Get-Content $log -ErrorAction SilentlyContinue | Select-Object -Last 40; throw "Installation ($name) fehlgeschlagen (Code $($run.ExitCode))" }
    return $log
}

function AppEntries() {
    # Eintraege unter "Installierte Apps", die zu dieser App gehoeren (alter und neuer Name)
    return @(Get-ChildItem $uninstallRoot | ForEach-Object { Get-ItemProperty -LiteralPath $_.PSPath } |
        Where-Object { $_.DisplayName -eq $appName -or $_.DisplayName -eq $oldAppName -or $_.PSChildName -eq "Uebersichten-Ersteller" })
}

if ($Previous) {
    $Previous = (Resolve-Path $Previous).Path
    foreach ($dir in $target, $data, $oldTarget, $oldData) {
        if (Test-Path $dir) { throw "Update-Test nur auf einem Rechner ohne vorhandene Installation bzw. Daten: $dir existiert" }
    }
    Write-Host "0. Vorversion installieren: $Previous"
    Install $Previous "vorversion" | Out-Null
    $oldEntry = Get-ItemProperty -LiteralPath $appKey
    # Version nach SemVer vergleichen (nie per Textmuster): 2.6.0 und neuer legen dieselben Daten an
    $previousVersion = [version]"0.0"
    # Vorabversionen (z. B. 3.0.0-beta.2): verglichen wird die Versionsnummer ohne Zusatz
    if (-not [version]::TryParse(([string]$oldEntry.DisplayVersion).Split('-')[0], [ref]$previousVersion)) { throw "Version der Vorversion unbekannt: $($oldEntry.DisplayVersion)" }
    if (Test-Path (Join-Path $oldTarget "app\start.py")) {
        $previousKind = "2.2"
        if (-not (Test-Path $oldShortcut)) { throw "Verknuepfung der Vorversion fehlt: $oldShortcut" }
        Write-Host "   installiert: $($oldEntry.DisplayName) $($oldEntry.DisplayVersion) in $oldTarget"
        # Benutzerdaten wie von Version 2.2 (Einstellungen, Vorlagen, Kundenverlauf, Regeln)
        New-Item -ItemType Directory -Path (Join-Path $oldData "logos") -Force | Out-Null
        $json = '{"gesehen": "2.2.0", "theme": "dark", "vorlagen": [{"name": "Standard", "titel": "Vertragsübersicht"}], "kunden": [{"kd": "4711", "name": "Müller GmbH"}], "regeln": [{"enthaelt": "Hott-KI", "zyklus": "jährlich"}]}'
        [IO.File]::WriteAllText((Join-Path $oldData "gui-config.json"), $json, (New-Object Text.UTF8Encoding $false))
        [IO.File]::WriteAllBytes((Join-Path $oldData "logos\kunde.png"), [byte[]](0..255))
        $oldHashes = @{}
        Get-ChildItem $oldData -Recurse -File | ForEach-Object { $oldHashes[$_.FullName.Substring($oldData.Length)] = (Get-FileHash $_.FullName -Algorithm SHA256).Hash }
    } elseif ((Test-Path (Join-Path $target "app\start.py")) -and $previousVersion -ge [version]"2.5") {
        $previousKind = if ($previousVersion -ge [version]"2.6") { "2.6" } else { "2.5" }
        if (-not (Test-Path $shortcut)) { throw "Verknuepfung der Vorversion fehlt: $shortcut" }
        Write-Host "   installiert: $($oldEntry.DisplayName) $($oldEntry.DisplayVersion) in $target"
        # Benutzerdaten wie von PDF Tool 2.5: wie 2.4, dazu Stapel-Einstellungen; ausserdem ein
        # gespeicherter Vertragsstand (Benutzerdaten von 2.6 – ein Update darf ihn nie loeschen).
        # Von 2.6.0 zusaetzlich: eine aktive Kundenakte.
        New-Item -ItemType Directory -Path $data -Force | Out-Null
        $seen = if ($previousKind -eq "2.6") { $oldEntry.DisplayVersion } else { "2.5.0" }
        $active = if ($previousKind -eq "2.6") { ', "kunde_aktiv": "6f1c1d2e-0000-4000-8000-000000000024", "fenster": {"w": 1200, "h": 800, "x": 40, "y": 30, "max": false}' } else { "" }
        $json = '{"gesehen": "' + $seen + '", "theme": "dark", "vorlagen": [{"name": "Quer", "format": "quer", "titel": "Vertragsübersicht"}], "bausteine": [{"name": "Gruß", "text": "Mit freundlichen Grüßen"}], "regeln": [{"enthaelt": "Hott-KI", "zyklus": "jährlich"}, {"enthaelt": "Cloud", "zyklus": "monatlich"}], "kopfzeile": "Kopf fett", "kopfzeile_format": {"version": 1, "text": "Kopf fett", "spans": [{"start": 0, "end": 9, "font": "Helvetica", "size": 10, "color": "#B51F1F", "bold": true, "italic": false, "underline": false, "strike": false}], "paragraphs": [{"start": 0, "end": 9, "alignment": "left"}]}, "reparatur_ausgabe": "ordner", "reparatur_ordner": "C:\\Reparatur", "ordner_reparatur": "C:\\Quelle", "kunden_sortierung": "company", "kunden_auto_uebernehmen": false, "stapel_zielordner": "C:\\Stapel", "stapel_vorlage": "Quer", "stapel_logo": "", "stapel_unterordner": true, "stapel_kunden_zielordner": false, "stapel_konflikt": "skip"' + $active + '}'
        $seedFile = Join-Path $data "gui-config.json"
        [IO.File]::WriteAllText($seedFile, $json, (New-Object Text.UTF8Encoding $false))
        $akten = '{"schema_version": 2, "customers": [{"id": "6f1c1d2e-0000-4000-8000-000000000024", "company": "Muster GmbH", "number": "10042", "emails": ["rechnung@muster.de", "buchhaltung@muster.de"], "note": "Stammkunde", "logo": "", "target_dir": "", "template": "Quer", "template_auto": true, "header": null, "footer": {"text": "Kunde Muster\nZeile 2", "format": {"version": 1, "text": "Kunde Muster\nZeile 2", "spans": [{"start": 0, "end": 12, "font": "Helvetica", "size": 8, "color": "#333333", "bold": false, "italic": true, "underline": false, "strike": false}, {"start": 12, "end": 20, "font": "Helvetica", "size": 8, "color": "#333333", "bold": false, "italic": false, "underline": false, "strike": false}], "paragraphs": [{"start": 0, "end": 12, "alignment": "center"}, {"start": 13, "end": 20, "alignment": "center"}]}}, "last_excel": "", "last_pdf": "", "last_used_at": "2026-09-01T10:00:00.000000+02:00", "created_at": "2026-08-01T10:00:00.000000+02:00", "updated_at": "2026-08-01T10:00:00.000000+02:00", "origin": ""}]}'
        $storeFile = Join-Path $data "kundenakten.json"
        [IO.File]::WriteAllText($storeFile, $akten, (New-Object Text.UTF8Encoding $false))
        $historyDir = Join-Path $data "contract-history\6f1c1d2e-0000-4000-8000-000000000024"
        New-Item -ItemType Directory -Path $historyDir -Force | Out-Null
        $stand = '{"schema_version": 1, "id": "d35c1e20ea374713b2fbeff305bf9621", "customer_id": "6f1c1d2e-0000-4000-8000-000000000024", "created_at": "2026-09-01T10:00:00+02:00", "last_exported_at": "2026-09-01T10:00:00+02:00", "export_count": 1, "content_hash": "2d2bffa9c47a778250e981b95d4bbf461f270d0e5158b29968309383eb00d9a1", "customer_label": "Muster GmbH · 10042", "source": {"excel_path": "C:\\Listen\\muster.xlsx", "excel_sha256": "", "pdf_path": "C:\\PDF\\Vertragsuebersicht_Kd10042.pdf"}, "contracts": [{"contract_number": "10001", "effective": {"contract_type": "Softwarepflegevertrag", "description": "Warenwirtschaft", "start_date": "2024-01-01", "billing_cycle": "jährlich", "net_amount": "250.00", "net_text": "250,00", "payment_method": "Lastschrift"}, "raw": {"Vertrag-Nr.": "10001"}, "source_row": null}]}'
        $historyFile = Join-Path $historyDir "20260901T100000000000-d35c1e20.json"
        [IO.File]::WriteAllText($historyFile, $stand, (New-Object Text.UTF8Encoding $false))
        $seedHash = (Get-FileHash $seedFile -Algorithm SHA256).Hash
        $storeHash = (Get-FileHash $storeFile -Algorithm SHA256).Hash
        $historyHash = (Get-FileHash $historyFile -Algorithm SHA256).Hash
    } elseif ((Test-Path (Join-Path $target "app\start.py")) -and $previousVersion -ge [version]"2.4") {
        $previousKind = "2.4"
        if (-not (Test-Path $shortcut)) { throw "Verknuepfung der Vorversion fehlt: $shortcut" }
        Write-Host "   installiert: $($oldEntry.DisplayName) $($oldEntry.DisplayVersion) in $target"
        # Benutzerdaten wie von PDF Tool 2.4: Kundenakte mit formatierter eigener Fusszeile und Vorlage,
        # formatierte Kopfzeile, Vorlagen, Textbausteine, Regeln, Einstellungen von "PDF reparieren"
        New-Item -ItemType Directory -Path $data -Force | Out-Null
        $json = '{"gesehen": "2.4.0", "theme": "dark", "vorlagen": [{"name": "Quer", "format": "quer", "titel": "Vertragsübersicht"}], "bausteine": [{"name": "Gruß", "text": "Mit freundlichen Grüßen"}], "regeln": [{"enthaelt": "Hott-KI", "zyklus": "jährlich"}, {"enthaelt": "Cloud", "zyklus": "monatlich"}], "kopfzeile": "Kopf fett", "kopfzeile_format": {"version": 1, "text": "Kopf fett", "spans": [{"start": 0, "end": 9, "font": "Helvetica", "size": 10, "color": "#B51F1F", "bold": true, "italic": false, "underline": false, "strike": false}], "paragraphs": [{"start": 0, "end": 9, "alignment": "left"}]}, "reparatur_ausgabe": "ordner", "reparatur_ordner": "C:\\Reparatur", "ordner_reparatur": "C:\\Quelle", "kunden_sortierung": "company", "kunden_auto_uebernehmen": false}'
        $seedFile = Join-Path $data "gui-config.json"
        [IO.File]::WriteAllText($seedFile, $json, (New-Object Text.UTF8Encoding $false))
        $akten = '{"schema_version": 2, "customers": [{"id": "6f1c1d2e-0000-4000-8000-000000000024", "company": "Muster GmbH", "number": "10042", "emails": ["rechnung@muster.de", "buchhaltung@muster.de"], "note": "Stammkunde", "logo": "", "target_dir": "", "template": "Quer", "template_auto": true, "header": null, "footer": {"text": "Kunde Muster\nZeile 2", "format": {"version": 1, "text": "Kunde Muster\nZeile 2", "spans": [{"start": 0, "end": 12, "font": "Helvetica", "size": 8, "color": "#333333", "bold": false, "italic": true, "underline": false, "strike": false}, {"start": 12, "end": 20, "font": "Helvetica", "size": 8, "color": "#333333", "bold": false, "italic": false, "underline": false, "strike": false}], "paragraphs": [{"start": 0, "end": 12, "alignment": "center"}, {"start": 13, "end": 20, "alignment": "center"}]}}, "last_excel": "", "last_pdf": "", "last_used_at": "2026-09-01T10:00:00.000000+02:00", "created_at": "2026-08-01T10:00:00.000000+02:00", "updated_at": "2026-08-01T10:00:00.000000+02:00", "origin": ""}]}'
        $storeFile = Join-Path $data "kundenakten.json"
        [IO.File]::WriteAllText($storeFile, $akten, (New-Object Text.UTF8Encoding $false))
        $seedHash = (Get-FileHash $seedFile -Algorithm SHA256).Hash
        $storeHash = (Get-FileHash $storeFile -Algorithm SHA256).Hash
    } elseif (Test-Path (Join-Path $target "app\start.py")) {
        $previousKind = "2.3"
        if (-not (Test-Path $shortcut)) { throw "Verknuepfung der Vorversion fehlt: $shortcut" }
        Write-Host "   installiert: $($oldEntry.DisplayName) $($oldEntry.DisplayVersion) in $target"
        # Benutzerdaten wie von PDF Tool 2.3: Kundenverlauf (ein Eintrag mit formatierter eigener
        # Fusszeile, einer mit leerer Fusszeile aus aelteren Versionen), Vorlagen, Textbausteine, Regeln
        New-Item -ItemType Directory -Path $data -Force | Out-Null
        $json = '{"gesehen": "2.3.0", "theme": "dark", "vorlagen": [{"name": "Standard", "titel": "Vertragsübersicht"}], "bausteine": [{"name": "Gruß", "text": "Mit freundlichen Grüßen"}], "regeln": [{"enthaelt": "Hott-KI", "zyklus": "jährlich"}], "kunden": [{"firmenname": "Muster GmbH", "kundennummer": "10042", "rechnungsempfaenger": "Rechnung@Muster.de", "excel": "", "logo": "", "fusszeile": "Kunde Muster\nZeile 2", "fusszeile_format": {"version": 1, "text": "Kunde Muster\nZeile 2", "spans": [{"start": 0, "end": 12, "font": "Helvetica", "size": 8, "color": "#333333", "bold": false, "italic": true, "underline": false, "strike": false}, {"start": 12, "end": 20, "font": "Helvetica", "size": 8, "color": "#333333", "bold": false, "italic": false, "underline": false, "strike": false}], "paragraphs": [{"start": 0, "end": 12, "alignment": "center"}, {"start": 13, "end": 20, "alignment": "center"}]}, "kopfzeile": "", "pdf": ""}, {"firmenname": "Alt AG", "kundennummer": "1", "rechnungsempfaenger": "", "excel": "", "logo": "", "fusszeile": "", "kopfzeile": "", "pdf": ""}]}'
        $seedFile = Join-Path $data "gui-config.json"
        [IO.File]::WriteAllText($seedFile, $json, (New-Object Text.UTF8Encoding $false))
        $seedHash = (Get-FileHash $seedFile -Algorithm SHA256).Hash
    } else {
        throw "Vorversion wurde weder in $oldTarget noch in $target installiert"
    }
}

Write-Host "1. Stille Installation: $Setup"
$log = Install $Setup "installation"
foreach ($file in "runtime\python.exe", "runtime\pythonw.exe", "app\start.py", "app\qml_rc.py", "app\engine.py", "app\excelstyle.py", "app\richtext.py", "app\pdffonts.py", "app\winsys.py", "app\qtapp\application.py", "app\qtapp\app.py", "app\qtapp\repair.py", "app\qtapp\contracts\overview.py", "app\qtapp\contracts\batch.py", "app\qtapp\contracts\customers.py", "app\qtapp\contracts\comparison.py", "app\tools\registry.py", "app\tools\contract_overview\history\repository.py", "app\tools\pdf_repair\engine.py", "app\tools\pdf_repair\process.py", "app\tools\pdf_repair\presentation.py", "app\tools\pdf_repair\recovery\rebuild.py", "app\qtapp\updates.py", "app\updater\service.py", "app\updater\launch.py", "runtime\Lib\site-packages\PySide6\QtNetwork.pyd", "runtime\Lib\site-packages\PySide6\plugins\tls\qschannelbackend.dll", "runtime\Lib\site-packages\pikepdf\__init__.py", "runtime\Lib\site-packages\pypdfium2_raw\pdfium.dll", "runtime\Lib\site-packages\pypdf\__init__.py", "runtime\Lib\site-packages\PySide6\QtQuick.pyd", "runtime\Lib\site-packages\PySide6\Qt6Quick.dll", "runtime\Lib\site-packages\PySide6\plugins\platforms\qwindows.dll", "runtime\Lib\site-packages\PySide6\qml\QtQuick\Controls\Basic\qmldir", "runtime\Lib\site-packages\shiboken6\Shiboken.pyd", "runtime\Lib\site-packages\PySide6\QtPrintSupport.pyd", "runtime\Lib\site-packages\PySide6\Qt6PrintSupport.dll", "runtime\Lib\site-packages\fontTools\__init__.py", "app\qtapp\instance.py", "app\qtapp\reader\controller.py", "app\qtapp\reader\document.py", "app\tools\pdf_editor\textedit.py", "app\tools\pdf_editor\save.py", "assets\icon.ico", "assets\hott_logo_final.png", "VERSION", "unins000.exe") {
    if (-not (Test-Path (Join-Path $target $file))) { throw "Nach der Installation fehlt: $file" }
}
# Seit 2.7.0 ohne Tk-Oberflaeche: auch bei einem Update bleiben keine alten Programmteile zurueck
foreach ($file in "app\vertragdesk.py", "app\ui", "app\qml", "runtime\tcl", "runtime\DLLs\_tkinter.pyd", "runtime\DLLs\tk86t.dll", "runtime\Lib\tkinter", "runtime\Lib\site-packages\PySide6\opengl32sw.dll", "runtime\Lib\site-packages\PySide6\designer.exe") {
    if (Test-Path (Join-Path $target $file)) { throw "Nach der Installation noch vorhanden: $file" }
}
if (-not (Get-ChildItem (Join-Path $target "runtime\Lib\site-packages\pikepdf.libs") -Filter "qpdf*.dll")) { throw "qpdf-Bibliothek fehlt" }
# Texterkennung (OCR): Tesseract mit seinen Bibliotheken, Sprachdaten und Lizenz im eigenen Ordner
foreach ($file in "ocr\tesseract.exe", "ocr\libtesseract-5.dll", "ocr\libleptonica-6.dll", "ocr\tessdata\deu.traineddata", "ocr\tessdata\eng.traineddata", "ocr\tessdata\osd.traineddata", "ocr\LICENSE.txt", "LICENSE", "THIRD_PARTY_LICENSES.md") {
    if (-not (Test-Path (Join-Path $target $file))) { throw "Nach der Installation fehlt: $file" }
}
# KI-Assistent: Laufzeit (llama.cpp) mit Rechenwerken und Lizenzen im eigenen Ordner – Sprachmodelle nicht im Setup
foreach ($file in "ai\llama-server.exe", "ai\LICENSES.txt") {
    if (-not (Test-Path (Join-Path $target $file))) { throw "Nach der Installation fehlt: $file" }
}
if (-not (Get-ChildItem (Join-Path $target "ai") -Filter "ggml-cpu-*.dll")) { throw "Rechenwerke der KI-Laufzeit fehlen (ai\ggml-cpu-*.dll)" }
if (Get-ChildItem $target -Recurse -Filter "*.gguf" -ErrorAction SilentlyContinue) { throw "Ein Sprachmodell liegt im Programmordner (gehoert nicht ins Setup)" }
if (-not (Test-Path $shortcut)) { throw "Startmenue-Verknuepfung fehlt: $shortcut" }
$version = (Get-Content (Join-Path $target "VERSION") -Raw).Trim()
$entries = AppEntries
if ($entries.Count -ne 1) { throw "Erwartet genau einen Eintrag unter 'Installierte Apps', gefunden: $($entries.Count) ($(($entries | ForEach-Object { $_.DisplayName }) -join ', '))" }
$entry = Get-ItemProperty -LiteralPath $appKey
if ($entry.DisplayName -ne $appName) { throw "Name unter 'Installierte Apps': $($entry.DisplayName)" }
if ($entry.DisplayVersion -ne $version) { throw "Version unter 'Installierte Apps': $($entry.DisplayVersion)" }
if ((($entry."Inno Setup: App Path") -replace '\\$', '') -ne $target) { throw "Installationsort laut Registrierung: $($entry.'Inno Setup: App Path')" }
Write-Host "   installiert: $($entry.DisplayName) $version in $target"
# »Oeffnen mit«: ProgID mit Befehl, Eintrag unter .pdf\OpenWithProgids, Standard-App unveraendert
$command = (Get-Item -LiteralPath (Join-Path $progIdKey "shell\open\command")).GetValue("")
if ($command -notlike "*$(Join-Path $target 'app\start.py')*" -or $command -notlike '*"%1"*') { throw "Befehl fuer 'Oeffnen mit': $command" }
if ((Get-Item -LiteralPath (Join-Path $progIdKey "shell\open")).GetValue("FriendlyAppName") -ne $appName) { throw "Name in 'Oeffnen mit' fehlt" }
if ($null -eq (Get-Item -LiteralPath $openWithKey).GetValue("PDFTool.Dokument")) { throw "PDF Tool fehlt unter .pdf\OpenWithProgids" }
if ((PdfDefault) -ne $pdfDefaultBefore) { throw "Das Setup hat die Standard-App fuer PDF-Dateien veraendert: $(PdfDefault) statt $pdfDefaultBefore" }
Write-Host "   'Oeffnen mit' fuer PDF-Dateien eingetragen, Standard-App unveraendert ($pdfDefaultBefore)"

if ($Previous -and $previousKind -eq "2.3") {
    Write-Host "2. Update von PDF Tool $($oldEntry.DisplayVersion) pruefen"
    if ($oldEntry.DisplayName -ne $appName) { throw "Vorversion unter 'Installierte Apps': $($oldEntry.DisplayName)" }
    # Die Uebernahme der Kundenakten erledigt die App beim Start – das Setup veraendert keine Benutzerdaten.
    if ((Get-FileHash $seedFile -Algorithm SHA256).Hash -ne $seedHash) { throw "Das Setup hat die Benutzerdaten veraendert" }
    if (Test-Path (Join-Path $data "kundenakten.json")) { throw "kundenakten.json vor dem ersten Start vorhanden" }
    Write-Host "   Programmdateien ersetzt, Benutzerdaten unveraendert"
}

if ($Previous -and ($previousKind -eq "2.5" -or $previousKind -eq "2.6")) {
    Write-Host "2. Update von PDF Tool $($oldEntry.DisplayVersion) pruefen"
    if ($oldEntry.DisplayName -ne $appName) { throw "Vorversion unter 'Installierte Apps': $($oldEntry.DisplayName)" }
    if ((Get-FileHash $seedFile -Algorithm SHA256).Hash -ne $seedHash) { throw "Das Setup hat die Einstellungen veraendert" }
    if ((Get-FileHash $storeFile -Algorithm SHA256).Hash -ne $storeHash) { throw "Das Setup hat die Kundenakten veraendert" }
    if (-not (Test-Path $historyFile) -or (Get-FileHash $historyFile -Algorithm SHA256).Hash -ne $historyHash) { throw "Das Setup hat den Vertragsstand veraendert oder geloescht" }
    Write-Host "   Programmdateien ersetzt, Einstellungen, Kundenakten und Vertragsstand unveraendert"
}

if ($Previous -and $previousKind -eq "2.4") {
    Write-Host "2. Update von PDF Tool $($oldEntry.DisplayVersion) pruefen"
    if ($oldEntry.DisplayName -ne $appName) { throw "Vorversion unter 'Installierte Apps': $($oldEntry.DisplayName)" }
    if ((Get-FileHash $seedFile -Algorithm SHA256).Hash -ne $seedHash) { throw "Das Setup hat die Einstellungen veraendert" }
    if ((Get-FileHash $storeFile -Algorithm SHA256).Hash -ne $storeHash) { throw "Das Setup hat die Kundenakten veraendert" }
    Write-Host "   Programmdateien ersetzt, Einstellungen und Kundenakten unveraendert"
}

if ($Previous -and $previousKind -eq "2.2") {
    Write-Host "2. Update vom Uebersichten-Ersteller pruefen"
    if (Test-Path $oldTarget) { throw "Alter Programmordner besteht noch: $oldTarget ($((Get-ChildItem $oldTarget -Recurse | Select-Object -First 5 | ForEach-Object { $_.FullName }) -join ', '))" }
    if (Test-Path $oldShortcut) { throw "Alte Startmenue-Verknuepfung besteht noch: $oldShortcut" }
    if (Test-Path (Join-Path $desktop "$oldAppName.lnk")) { throw "Alte Desktop-Verknuepfung besteht noch" }
    if (-not (Test-Path (Join-Path $desktop "$appName.lnk"))) { throw "Desktop-Verknuepfung 'PDF Tool' fehlt (Auswahl der Vorversion uebernommen)" }
    # Benutzerdaten: die App uebernimmt sie beim ersten Start (wie beim Doppelklick auf die Verknuepfung)
    $dataDir = & (Join-Path $target "runtime\python.exe") -s -c "import sys; sys.path.insert(0, sys.argv[1]); import appstate; print(appstate.DATA_DIR)" (Join-Path $target "app")
    if ($LASTEXITCODE -ne 0) { throw "Datenuebernahme fehlgeschlagen" }
    if (($dataDir | Select-Object -Last 1).Trim() -ne $data) { throw "Datenordner nach dem Update: $dataDir" }
    foreach ($name in $oldHashes.Keys) {
        $copy = Join-Path $data $name.TrimStart('\')
        if (-not (Test-Path $copy)) { throw "Nicht uebernommen: $name" }
        if ((Get-FileHash $copy -Algorithm SHA256).Hash -ne $oldHashes[$name]) { throw "Uebernommene Datei weicht ab: $name" }
        if ((Get-FileHash (Join-Path $oldData $name.TrimStart('\')) -Algorithm SHA256).Hash -ne $oldHashes[$name]) { throw "Alte Datei wurde veraendert: $name" }
    }
    if (-not (Test-Path (Join-Path $data "migration-backup-2.2.0.zip"))) { throw "Sicherung migration-backup-2.2.0.zip fehlt" }
    if (-not (Test-Path (Join-Path $data "migration.json"))) { throw "Vermerk migration.json fehlt" }
    Write-Host "   alter Programmordner entfernt, Verknuepfungen umbenannt, $($oldHashes.Count) Dateien mit Sicherung uebernommen"
}

Write-Host "3. Installierte Laufzeit: Module, Vertragsuebersicht, PDF-Reparatur, Programmstart"
& (Join-Path $target "runtime\python.exe") -s (Join-Path $PSScriptRoot "smoke_runtime.py") --app (Join-Path $target "app") --ui
if ($LASTEXITCODE -ne 0) { throw "Pruefung der installierten Laufzeit fehlgeschlagen (Code $LASTEXITCODE)" }

Write-Host "4. Start wie ueber die Verknuepfung"
$errorLog = Join-Path $data "fehler.log"
Remove-Item $errorLog -ErrorAction SilentlyContinue
$app = Start-Process -FilePath (Join-Path $target "runtime\pythonw.exe") -ArgumentList "-s", "-OO", "`"$(Join-Path $target 'app\start.py')`"" -WorkingDirectory (Join-Path $target "app") -PassThru
Start-Sleep -Seconds 15
if ($app.HasExited) { throw "Die App hat sich beim Start beendet (Code $($app.ExitCode))" }
if (Test-Path $errorLog) { throw "Fehler beim Start: $(Get-Content $errorLog -Raw)" }
Stop-Process -Id $app.Id -Force
Start-Sleep -Seconds 2
Write-Host "   App lief ohne Fehler"
Write-Host "4b. 'Oeffnen mit': Start mit einer PDF, zweiter Start reicht seine PDF weiter"
$pdfDir = Join-Path $temp "pdf-tool-oeffnen-mit"
New-Item -ItemType Directory -Force -Path $pdfDir | Out-Null
$pdfA = Join-Path $pdfDir "Erste Datei.pdf"
$pdfB = Join-Path $pdfDir "Zweite Datei.pdf"
& (Join-Path $target "runtime\python.exe") -s -c "import sys, pikepdf; [(lambda p: (p.add_blank_page(), p.save(f)))(pikepdf.new()) for f in sys.argv[1:]]" $pdfA $pdfB
if ($LASTEXITCODE -ne 0) { throw "Test-PDFs konnten nicht erzeugt werden" }
Remove-Item $errorLog -ErrorAction SilentlyContinue
$first = Start-Process -FilePath (Join-Path $target "runtime\pythonw.exe") -ArgumentList "-s", "-OO", "`"$(Join-Path $target 'app\start.py')`"", "`"$pdfA`"" -WorkingDirectory (Join-Path $target "app") -PassThru
Start-Sleep -Seconds 15
if ($first.HasExited) { throw "Die App hat sich beim Start mit einer PDF beendet (Code $($first.ExitCode))" }
$second = Start-Process -FilePath (Join-Path $target "runtime\pythonw.exe") -ArgumentList "-s", "-OO", "`"$(Join-Path $target 'app\start.py')`"", "`"$pdfB`"" -WorkingDirectory (Join-Path $target "app") -PassThru
$null = $second.Handle  # Handle sofort holen, sonst ist ExitCode nach dem Ende leer
if (-not $second.WaitForExit(30000)) { Stop-Process -Id $second.Id -Force; throw "Der zweite Start hat seine PDF nicht an die laufende App weitergereicht" }
if ($second.ExitCode -ne 0) { throw "Zweiter Start endete mit Code $($second.ExitCode)" }
if ($first.HasExited) { throw "Die laufende App hat sich beim Weiterreichen beendet" }
if (Test-Path $errorLog) { throw "Fehler beim Start mit einer PDF: $(Get-Content $errorLog -Raw)" }
Stop-Process -Id $first.Id -Force
Start-Sleep -Seconds 2
Remove-Item $pdfDir -Recurse -Force -ErrorAction SilentlyContinue
Write-Host "   App startete mit der PDF, der zweite Start endete nach dem Weiterreichen"
# Die automatische Update-Pruefung laeuft wenige Sekunden nach dem Start im Hintergrund (nur lesend).
# Offline oder bei einem Anfragelimit bleibt sie still - das ist nur ein Hinweis, kein Fehler.
if (Test-Path (Join-Path $updates "releases.json")) {
    Write-Host "   Automatische Update-Pruefung im Hintergrund: erfolgreich (HTTPS zu GitHub)"
} else {
    Write-Host "   Hinweis: keine automatische Update-Pruefung erfolgt (offline oder GitHub-Anfragelimit)"
}

if ($Previous -and $previousKind -eq "2.3") {
    # Seit 2.6.1 ist die Kundenakte optional und zunaechst aus: der Kundenverlauf bleibt unangetastet.
    Write-Host "   Kundenakte aus: Kundenverlauf unveraendert erhalten"
    $store = Join-Path $data "kundenakten.json"
    if (Test-Path $store) { throw "kundenakten.json angelegt, obwohl die Kundenakte aus ist" }
    $cfgFile = Join-Path $data "gui-config.json"
    $cfg = Get-Content $cfgFile -Raw -Encoding UTF8 | ConvertFrom-Json
    if (@($cfg.kunden).Count -ne 2) { throw "Kundenverlauf ging verloren, obwohl die Kundenakte aus ist" }
    if ($cfg.kundenakte_verwenden -eq $true) { throw "Kundenakte nach dem Update eingeschaltet" }
    # Einschalten (wie in den Einstellungen) und erneut starten: jetzt wird uebernommen
    $cfg | Add-Member -NotePropertyName "kundenakte_verwenden" -NotePropertyValue $true -Force
    [IO.File]::WriteAllText($cfgFile, ($cfg | ConvertTo-Json -Depth 32), (New-Object Text.UTF8Encoding $false))
    $seedHash = (Get-FileHash $cfgFile -Algorithm SHA256).Hash
    $app = Start-Process -FilePath (Join-Path $target "runtime\pythonw.exe") -ArgumentList "-s", "-OO", "`"$(Join-Path $target 'app\start.py')`"" -WorkingDirectory (Join-Path $target "app") -PassThru
    Start-Sleep -Seconds 15
    if ($app.HasExited) { throw "Die App hat sich nach dem Einschalten der Kundenakte beendet (Code $($app.ExitCode))" }
    if (Test-Path $errorLog) { throw "Fehler beim Start: $(Get-Content $errorLog -Raw)" }
    Stop-Process -Id $app.Id -Force
    Start-Sleep -Seconds 2
    Write-Host "   Kundenakte 2.0: Uebernahme des Kundenverlaufs nach dem Einschalten pruefen"
    if (-not (Test-Path $store)) { throw "kundenakten.json fehlt nach dem Start mit eingeschalteter Kundenakte" }
    $akten = Get-Content $store -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($akten.schema_version -ne 2) { throw "schema_version: $($akten.schema_version)" }
    if (@($akten.customers).Count -ne 2) { throw "Erwartet 2 Kundenakten, gefunden: $(@($akten.customers).Count)" }
    $muster = @($akten.customers | Where-Object { $_.number -eq "10042" })[0]
    if (-not $muster -or $muster.company -ne "Muster GmbH") { throw "Kundenakte 'Muster GmbH' fehlt" }
    if ((@($muster.emails) -join ",") -ne "rechnung@muster.de") { throw "E-Mail-Zuordnung: $(@($muster.emails) -join ',')" }
    if ($muster.footer.text -ne "Kunde Muster`nZeile 2") { throw "Eigene Fusszeile nicht uebernommen: $($muster.footer.text)" }
    if (-not (@($muster.footer.format.spans) | Where-Object { $_.italic -eq $true })) { throw "Formatierung der Fusszeile ging verloren" }
    $altAg = @($akten.customers | Where-Object { $_.number -eq "1" })[0]
    if (-not $altAg -or $null -ne $altAg.footer) { throw "Leere Fusszeile aus 2.3 wurde uebernommen" }
    $backup = @(Get-ChildItem (Join-Path $data "sicherungen") -Filter "gui-config-vor-kundenakte-*.json" -ErrorAction SilentlyContinue)
    if ($backup.Count -ne 1) { throw "Sicherung vor der Uebernahme fehlt" }
    if ((Get-FileHash $backup[0].FullName -Algorithm SHA256).Hash -ne $seedHash) { throw "Sicherung weicht von den Einstellungen der Vorversion ab" }
    $cfg = Get-Content (Join-Path $data "gui-config.json") -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($cfg.PSObject.Properties.Name -contains "kunden") { throw "Alter Kundenverlauf steht noch in gui-config.json" }
    if (@($cfg.vorlagen)[0].name -ne "Standard") { throw "Vorlagen gingen verloren" }
    if (@($cfg.bausteine)[0].text -ne "Mit freundlichen $([char]0x0047)r$([char]0x00FC)$([char]0x00DF)en") { throw "Textbausteine gingen verloren" }
    if (-not ([string]$cfg.fusszeile).StartsWith("Die oben aufgef$([char]0x00FC)hrte Auflistung")) { throw "Standard-Fusszeile fehlt: $($cfg.fusszeile)" }
    Write-Host "   2 Kundenakten mit Sicherung $($backup[0].Name) uebernommen; Formatierung, Standard-Fusszeile, Vorlagen und Textbausteine erhalten"
}

if ($Previous -and ($previousKind -eq "2.5" -or $previousKind -eq "2.6")) {
    Write-Host "   Update von $($previousKind): Einstellungen, Kundenakten, Vorlagen, Rich Text, Stapel- und Reparatur-Einstellungen, Vertragsstand pruefen"
    if ((Get-FileHash $storeFile -Algorithm SHA256).Hash -ne $storeHash) { throw "Kundenakten wurden beim Start veraendert" }
    if ((Get-FileHash $historyFile -Algorithm SHA256).Hash -ne $historyHash) { throw "Vertragsstand wurde beim Start veraendert" }
    $staende = @(Get-ChildItem (Join-Path $data "contract-history") -Recurse -File)
    if ($staende.Count -ne 1) { throw "Erwartet genau einen Vertragsstand (keine kuenstlichen Staende), gefunden: $($staende.Count)" }
    $gelesen = & (Join-Path $target "runtime\python.exe") -s -c "import sys, pathlib; sys.path.insert(0, sys.argv[1]); import appstate; from tools.contract_overview.history.repository import FOLDER, HistoryStore; store = HistoryStore(pathlib.Path(appstate.CONFIG_FILE).parent / FOLDER); items = store.snapshots(sys.argv[2]); print(len(items), items[0].contracts[0].contract_number if items else '-')" (Join-Path $target "app") "6f1c1d2e-0000-4000-8000-000000000024"
    if ($LASTEXITCODE -ne 0 -or ($gelesen | Select-Object -Last 1).Trim() -ne "1 10001") { throw "Vertragsstand ist fuer die App nicht lesbar: $gelesen" }
    $cfg = Get-Content (Join-Path $data "gui-config.json") -Raw -Encoding UTF8 | ConvertFrom-Json
    if (@($cfg.vorlagen)[0].name -ne "Quer" -or @($cfg.vorlagen)[0].format -ne "quer") { throw "Vorlagen gingen verloren" }
    if (@($cfg.bausteine)[0].text -ne "Mit freundlichen $([char]0x0047)r$([char]0x00FC)$([char]0x00DF)en") { throw "Textbausteine gingen verloren" }
    if (@($cfg.regeln).Count -ne 2) { throw "Zyklus-Regeln gingen verloren" }
    if ($cfg.kopfzeile -ne "Kopf fett" -or -not (@($cfg.kopfzeile_format.spans) | Where-Object { $_.bold -eq $true })) { throw "Formatierte Kopfzeile ging verloren" }
    if ($cfg.reparatur_ausgabe -ne "ordner" -or $cfg.reparatur_ordner -ne "C:\Reparatur" -or $cfg.ordner_reparatur -ne "C:\Quelle") { throw "Einstellungen von 'PDF reparieren' gingen verloren" }
    if ($cfg.stapel_zielordner -ne "C:\Stapel" -or $cfg.stapel_vorlage -ne "Quer" -or $cfg.stapel_unterordner -ne $true -or $cfg.stapel_kunden_zielordner -ne $false -or $cfg.stapel_konflikt -ne "skip") { throw "Stapel-Einstellungen gingen verloren" }
    if ($cfg.kunden_sortierung -ne "company") { throw "Sortierung der Kundenliste ging verloren" }
    if ($previousKind -eq "2.6" -and ($cfg.fenster.w -ne 1200 -or $cfg.fenster.h -ne 800)) { throw "Fensterlage der Vorversion wurde veraendert" }
    # Kundenakte zunaechst aus (Opt-in) – die Kundenakten bleiben unveraendert und lesbar
    if ($cfg.kundenakte_verwenden -eq $true) { throw "Kundenakte nach dem Update eingeschaltet" }
    $akten = & (Join-Path $target "runtime\python.exe") -s -c "import sys, pathlib; sys.path.insert(0, sys.argv[1]); import appstate; from tools.contract_overview.customers.repository import CustomerStore; store = CustomerStore.load(pathlib.Path(appstate.CONFIG_FILE).parent / 'kundenakten.json'); print(len(store), store.get(sys.argv[2]).company)" (Join-Path $target "app") "6f1c1d2e-0000-4000-8000-000000000024"
    if ($LASTEXITCODE -ne 0 -or ($akten | Select-Object -Last 1).Trim() -ne "1 Muster GmbH") { throw "Kundenakten sind fuer die App nicht lesbar: $akten" }
    Write-Host "   Kundenakte (aus, Daten unveraendert und lesbar), Vertragsstand (lesbar, kein neuer Stand), Vorlagen, Textbausteine, Regeln, Kopfzeile, Stapel- und Reparatur-Einstellungen erhalten"
}

if ($Previous -and $previousKind -eq "2.4") {
    Write-Host "   Update von 2.4: Einstellungen, Kundenakten, Vorlagen, Rich Text und Reparatur-Einstellungen pruefen"
    if ((Get-FileHash $storeFile -Algorithm SHA256).Hash -ne $storeHash) { throw "Kundenakten wurden beim Start veraendert" }
    $akten = Get-Content $storeFile -Raw -Encoding UTF8 | ConvertFrom-Json
    $muster = @($akten.customers)[0]
    if ($muster.company -ne "Muster GmbH" -or $muster.template -ne "Quer" -or (@($muster.emails) -join ",") -ne "rechnung@muster.de,buchhaltung@muster.de") { throw "Kundenakte veraendert" }
    if (-not (@($muster.footer.format.spans) | Where-Object { $_.italic -eq $true })) { throw "Formatierung der Fusszeile der Kundenakte ging verloren" }
    $cfg = Get-Content (Join-Path $data "gui-config.json") -Raw -Encoding UTF8 | ConvertFrom-Json
    if (@($cfg.vorlagen)[0].name -ne "Quer" -or @($cfg.vorlagen)[0].format -ne "quer") { throw "Vorlagen gingen verloren" }
    if (@($cfg.bausteine)[0].text -ne "Mit freundlichen $([char]0x0047)r$([char]0x00FC)$([char]0x00DF)en") { throw "Textbausteine gingen verloren" }
    if (@($cfg.regeln).Count -ne 2) { throw "Zyklus-Regeln gingen verloren" }
    if ($cfg.kopfzeile -ne "Kopf fett" -or -not (@($cfg.kopfzeile_format.spans) | Where-Object { $_.bold -eq $true })) { throw "Formatierte Kopfzeile ging verloren" }
    if ($cfg.reparatur_ausgabe -ne "ordner" -or $cfg.reparatur_ordner -ne "C:\Reparatur" -or $cfg.ordner_reparatur -ne "C:\Quelle") { throw "Einstellungen von 'PDF reparieren' gingen verloren" }
    if ($cfg.kunden_sortierung -ne "company") { throw "Sortierung der Kundenliste ging verloren" }
    Write-Host "   Kundenakte, Vorlagen, Textbausteine, Regeln, formatierte Kopfzeile und Reparatur-Einstellungen erhalten"
}

# Geladene Sprachmodelle (hier Attrappen) entfernt die Deinstallation – fremde Dateien im Ordner bleiben
if ($kiNew) {
    $models = Join-Path $ki "modelle"
    New-Item -ItemType Directory -Force -Path $models | Out-Null
    foreach ($name in "Qwen3.5-2B-Q4_K_M.gguf", "Qwen3.5-2B-Q4_K_M.gguf.sha256", "Qwen3.5-4B-Q4_K_M.gguf.part") {
        Set-Content -Path (Join-Path $models $name) -Value "Testattrappe" -Encoding ascii
    }
    Set-Content -Path (Join-Path $models "eigene-notiz.txt") -Value "nicht von PDF Tool" -Encoding ascii
}

Write-Host "5. Stille Deinstallation"
$uninstall = Start-Process -FilePath (Join-Path $target "unins000.exe") -ArgumentList "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART" -Wait -PassThru
if ($uninstall.ExitCode -ne 0) { throw "Deinstallation fehlgeschlagen (Code $($uninstall.ExitCode))" }
# Der Deinstaller laeuft als Kopie weiter: auf Programmordner und Registrierungseintrag warten
$deadline = (Get-Date).AddSeconds(90)
while (((Test-Path (Join-Path $target "app")) -or (AppEntries).Count -ne 0) -and ((Get-Date) -lt $deadline)) { Start-Sleep -Seconds 2 }
if (Test-Path (Join-Path $target "app")) { throw "Programmdateien sind nach der Deinstallation noch vorhanden" }
if (Test-Path (Join-Path $target "runtime")) { throw "Laufzeit ist nach der Deinstallation noch vorhanden" }
if (Test-Path $shortcut) { throw "Verknuepfung ist nach der Deinstallation noch vorhanden" }
if ((AppEntries).Count -ne 0) { throw "Eintrag unter 'Installierte Apps' ist nach der Deinstallation noch vorhanden" }
if (Test-Path $progIdKey) { throw "Eintrag fuer 'Oeffnen mit' ist nach der Deinstallation noch vorhanden" }
if ((Test-Path $openWithKey) -and ($null -ne (Get-Item -LiteralPath $openWithKey).GetValue("PDFTool.Dokument"))) { throw ".pdf\OpenWithProgids enthaelt nach der Deinstallation noch PDF Tool" }
if ((PdfDefault) -ne $pdfDefaultBefore) { throw "Standard-App fuer PDF-Dateien nach der Deinstallation veraendert" }
if (-not $pdfKeyBefore -and (Test-Path "HKCU:\Software\Classes\.pdf")) { throw "Der vom Setup angelegte Schluessel .pdf ist nach der Deinstallation noch vorhanden" }
if ($Previous -and -not (Test-Path (Join-Path $data "gui-config.json"))) { throw "Stille Deinstallation hat Benutzerdaten geloescht" }
if (Get-ChildItem $updates -ErrorAction SilentlyContinue | Where-Object { $_.Name -like "PDF-Tool-Setup-*" -or $_.Name -eq "releases.json" }) { throw "Heruntergeladene Updates sind nach der Deinstallation noch vorhanden" }
if (Test-Path (Join-Path $target "ai")) { throw "KI-Laufzeit ist nach der Deinstallation noch vorhanden" }
if ($kiNew) {
    if (Get-ChildItem $ki -Recurse -Filter "Qwen3.5-*" -ErrorAction SilentlyContinue) { throw "Sprachmodelle sind nach der Deinstallation noch vorhanden" }
    if (-not (Test-Path (Join-Path $ki "modelle\eigene-notiz.txt"))) { throw "Die Deinstallation hat eine fremde Datei im Ordner der Sprachmodelle geloescht" }
}

# Aufraeumen: nur, was dieser Test angelegt hat
foreach ($dir in $created) { if (Test-Path $dir) { Remove-Item $dir -Recurse -Force -ErrorAction SilentlyContinue } }
$mode = if ($Previous) { "Update von $($oldEntry.DisplayVersion) auf" } else { "Setup" }
Write-Host "OK: $mode $version installiert, geprueft und wieder entfernt"
