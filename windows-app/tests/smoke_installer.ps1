# Prueft das fertige Setup auf einem Windows-Rechner ohne eigenes Python:
#   1. still installieren
#   2. installierte Laufzeit pruefen (Module, PDF mit Excel-Fettschrift)
#   3. App-Module importieren und Programmstart (Hauptfenster)
#   4. echter Start wie ueber die Verknuepfung (pythonw.exe start.py)
#   5. still deinstallieren
#
# Aufruf: pwsh -File windows-app\tests\smoke_installer.ps1 -Setup windows-app\dist\Uebersichten-Ersteller-Setup-<Version>.exe

param([Parameter(Mandatory = $true)][string]$Setup)

$ErrorActionPreference = "Stop"
$Setup = (Resolve-Path $Setup).Path
$target = Join-Path $env:LOCALAPPDATA "Uebersichten-Ersteller"
$data = Join-Path $env:APPDATA "Uebersichten-Ersteller"
$temp = if ($env:RUNNER_TEMP) { $env:RUNNER_TEMP } else { $env:TEMP }
$appName = "$([char]0x00DC)bersichten-Ersteller"
$shortcut = Join-Path ([Environment]::GetFolderPath("Programs")) "$appName.lnk"

Write-Host "1. Stille Installation: $Setup"
$log = Join-Path $temp "setup-install.log"
$install = Start-Process -FilePath $Setup -ArgumentList "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/LOG=`"$log`"" -Wait -PassThru
if ($install.ExitCode -ne 0) { Get-Content $log -ErrorAction SilentlyContinue | Select-Object -Last 40; throw "Installation fehlgeschlagen (Code $($install.ExitCode))" }
foreach ($file in "runtime\python.exe", "runtime\pythonw.exe", "app\start.py", "app\vertragdesk.py", "app\engine.py", "app\excelstyle.py", "app\richtext.py", "app\pdffonts.py", "app\ui\richtext.py", "assets\icon.ico", "VERSION", "unins000.exe") {
    if (-not (Test-Path (Join-Path $target $file))) { throw "Nach der Installation fehlt: $file" }
}
if (-not (Test-Path $shortcut)) { throw "Startmenue-Verknuepfung fehlt: $shortcut" }
$version = (Get-Content (Join-Path $target "VERSION") -Raw).Trim()
Write-Host "   installiert: Version $version in $target"

Write-Host "2./3. Installierte Laufzeit, App-Module, PDF und Programmstart"
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

Write-Host "5. Stille Deinstallation"
$uninstall = Start-Process -FilePath (Join-Path $target "unins000.exe") -ArgumentList "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART" -Wait -PassThru
if ($uninstall.ExitCode -ne 0) { throw "Deinstallation fehlgeschlagen (Code $($uninstall.ExitCode))" }
$deadline = (Get-Date).AddSeconds(90)
while ((Test-Path (Join-Path $target "app")) -and ((Get-Date) -lt $deadline)) { Start-Sleep -Seconds 2 }
if (Test-Path (Join-Path $target "app")) { throw "Programmdateien sind nach der Deinstallation noch vorhanden" }
if (Test-Path (Join-Path $target "runtime")) { throw "Laufzeit ist nach der Deinstallation noch vorhanden" }
if (Test-Path $shortcut) { throw "Verknuepfung ist nach der Deinstallation noch vorhanden" }
Write-Host "OK: Setup $version installiert, geprueft und wieder entfernt"
