# Prueft das fertige Setup auf einem Windows-Rechner ohne eigenes Python:
#   0. nur mit -Previous: Vorversion installieren und Benutzerdaten anlegen –
#      Uebersichten-Ersteller 2.2.0 oder PDF Tool 2.3.0 (mit Kundenverlauf samt formatierter
#      Fusszeile, Vorlagen, Textbausteinen und Regeln)
#   1. still installieren (bzw. aktualisieren) und Installation pruefen:
#      Ordner, Verknuepfungen, genau ein Eintrag unter "Installierte Apps"
#   2. nur mit -Previous: 2.2.0 – alter Programmordner und alte Verknuepfungen entfernt,
#      Benutzerdaten mit Sicherung nach %APPDATA%\PDF-Tool uebernommen, alte Daten unveraendert;
#      2.3.0 – das Setup laesst die Benutzerdaten unangetastet
#   3. installierte Laufzeit pruefen (Module, Vertragsuebersicht, Kundenakte, Vorschau,
#      PDF-Reparatur, Programmstart)
#   4. echter Start wie ueber die Verknuepfung (pythonw.exe start.py); nach einem Update von
#      2.3.0: Kundenverlauf mit Sicherung zu Kundenakten uebernommen, Formatierung,
#      Standard-Fusszeile, Vorlagen und Textbausteine erhalten
#   5. still deinstallieren
#
# Aufruf:
#   pwsh -File windows-app\tests\smoke_installer.ps1 -Setup windows-app\dist\PDF-Tool-Setup-<Version>.exe
#   pwsh -File windows-app\tests\smoke_installer.ps1 -Setup ...\PDF-Tool-Setup-<Version>.exe -Previous ...\Uebersichten-Ersteller-Setup-2.2.0.exe
#   pwsh -File windows-app\tests\smoke_installer.ps1 -Setup ...\PDF-Tool-Setup-<Version>.exe -Previous ...\PDF-Tool-Setup-2.3.0.exe
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
$temp = if ($env:RUNNER_TEMP) { $env:RUNNER_TEMP } else { $env:TEMP }
$appName = "PDF Tool"
$oldAppName = "$([char]0x00DC)bersichten-Ersteller"
$programs = [Environment]::GetFolderPath("Programs")
$desktop = [Environment]::GetFolderPath("Desktop")
$shortcut = Join-Path $programs "$appName.lnk"
$oldShortcut = Join-Path $programs "$oldAppName.lnk"
$uninstallRoot = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall"
$appKey = Join-Path $uninstallRoot "{59C40061-D5E5-446D-ACB4-E077D3C71E1A}_is1"
$env:UE_DATA_DIR = $null
$env:UE_CONFIG_FILE = $null

# Ordner, die vor dem Test nicht existierten, werden am Ende entfernt (nie vorhandene Benutzerdaten).
$created = @($target, $data, $oldTarget, $oldData) | Where-Object { -not (Test-Path $_) }

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
foreach ($file in "runtime\python.exe", "runtime\pythonw.exe", "app\start.py", "app\vertragdesk.py", "app\engine.py", "app\excelstyle.py", "app\richtext.py", "app\pdffonts.py", "app\ui\richtext.py", "app\ui\pages\home.py", "app\tools\registry.py", "app\tools\contract_overview\controller.py", "app\tools\pdf_repair\engine.py", "app\tools\pdf_repair\process.py", "app\tools\pdf_repair\page.py", "runtime\Lib\site-packages\pikepdf\__init__.py", "runtime\Lib\site-packages\pypdfium2_raw\pdfium.dll", "assets\icon.ico", "assets\hott_logo_final.png", "VERSION", "unins000.exe") {
    if (-not (Test-Path (Join-Path $target $file))) { throw "Nach der Installation fehlt: $file" }
}
if (-not (Get-ChildItem (Join-Path $target "runtime\Lib\site-packages\pikepdf.libs") -Filter "qpdf*.dll")) { throw "qpdf-Bibliothek fehlt" }
if (-not (Test-Path $shortcut)) { throw "Startmenue-Verknuepfung fehlt: $shortcut" }
$version = (Get-Content (Join-Path $target "VERSION") -Raw).Trim()
$entries = AppEntries
if ($entries.Count -ne 1) { throw "Erwartet genau einen Eintrag unter 'Installierte Apps', gefunden: $($entries.Count) ($(($entries | ForEach-Object { $_.DisplayName }) -join ', '))" }
$entry = Get-ItemProperty -LiteralPath $appKey
if ($entry.DisplayName -ne $appName) { throw "Name unter 'Installierte Apps': $($entry.DisplayName)" }
if ($entry.DisplayVersion -ne $version) { throw "Version unter 'Installierte Apps': $($entry.DisplayVersion)" }
if ((($entry."Inno Setup: App Path") -replace '\\$', '') -ne $target) { throw "Installationsort laut Registrierung: $($entry.'Inno Setup: App Path')" }
Write-Host "   installiert: $($entry.DisplayName) $version in $target"

if ($Previous -and $previousKind -eq "2.3") {
    Write-Host "2. Update von PDF Tool $($oldEntry.DisplayVersion) pruefen"
    if ($oldEntry.DisplayName -ne $appName) { throw "Vorversion unter 'Installierte Apps': $($oldEntry.DisplayName)" }
    # Die Uebernahme der Kundenakten erledigt die App beim Start – das Setup veraendert keine Benutzerdaten.
    if ((Get-FileHash $seedFile -Algorithm SHA256).Hash -ne $seedHash) { throw "Das Setup hat die Benutzerdaten veraendert" }
    if (Test-Path (Join-Path $data "kundenakten.json")) { throw "kundenakten.json vor dem ersten Start vorhanden" }
    Write-Host "   Programmdateien ersetzt, Benutzerdaten unveraendert"
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

if ($Previous -and $previousKind -eq "2.3") {
    Write-Host "   Kundenakte 2.0: Uebernahme des Kundenverlaufs pruefen"
    $store = Join-Path $data "kundenakten.json"
    if (-not (Test-Path $store)) { throw "kundenakten.json fehlt nach dem ersten Start" }
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
if ($Previous -and -not (Test-Path (Join-Path $data "gui-config.json"))) { throw "Stille Deinstallation hat Benutzerdaten geloescht" }

# Aufraeumen: nur, was dieser Test angelegt hat
foreach ($dir in $created) { if (Test-Path $dir) { Remove-Item $dir -Recurse -Force -ErrorAction SilentlyContinue } }
$mode = if ($Previous) { "Update von $($oldEntry.DisplayVersion) auf" } else { "Setup" }
Write-Host "OK: $mode $version installiert, geprueft und wieder entfernt"
