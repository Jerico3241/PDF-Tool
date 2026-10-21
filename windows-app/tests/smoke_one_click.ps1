# Ein-Klick-Update auf echtem Windows: die veroeffentlichte Vorversion ist installiert und laeuft im Hintergrund,
# ihr eigener Updater-Code startet den Hilfsprozess mit dem Setup dieses Laufs - wie nach »Jetzt installieren«.
#
#   1. Vorversion still installieren, mit Windows-Start (--hintergrund) starten: App laeuft ohne Fenster
#   2. Setup dieses Laufs in den Update-Ordner legen (wie nach dem Download, Name PDF-Tool-Setup-<Version>.exe)
#   3. Code DER VORVERSION (updater.installer.Launcher, aus dem Programmordner) startet den Hilfsprozess mit
#      der Prozess-ID der laufenden App; danach endet die App (hier: beendet)
#   4. erwartet: stilles Setup mit Code 0 (»Update installiert« im Protokoll des Hilfsprozesses), kein sichtbares
#      Setup, danach die neue Version im App-Eintrag und PDF Tool neu gestartet
#   5. aufraeumen: App beenden, still deinstallieren
#
# Gilt erst, wenn die Vorversion den Hilfsprozess aus einer Kopie startet (seit 4.0.0-beta.3) - aeltere Vorversionen
# zeigen das Setup bekanntermassen sichtbar; dann wird der Test uebersprungen.
#
# Aufruf:
#   pwsh -File windows-app\tests\smoke_one_click.ps1 -Setup windows-app\dist\PDF-Tool-Setup-<Version>.exe -Previous ...\PDF-Tool-Setup-<Vorversion>.exe

param(
    [Parameter(Mandatory = $true)][string]$Setup,
    [Parameter(Mandatory = $true)][string]$Previous
)

$ErrorActionPreference = "Stop"
$Setup = (Resolve-Path $Setup).Path
$Previous = (Resolve-Path $Previous).Path
$target = Join-Path $env:LOCALAPPDATA "PDF-Tool"
$data = Join-Path $env:APPDATA "PDF-Tool"
$updates = Join-Path $env:LOCALAPPDATA "PDF-Tool-Updates"
$launcher = Join-Path $target "PDF-Tool.exe"
$runtimeExe = Join-Path $target "runtime\pythonw.exe"
$appKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\{59C40061-D5E5-446D-ACB4-E077D3C71E1A}_is1"
$temp = if ($env:RUNNER_TEMP) { $env:RUNNER_TEMP } else { $env:TEMP }
$version = ([IO.Path]::GetFileNameWithoutExtension($Setup) -replace '^PDF-Tool-Setup-', '')

function AppProcesses { @(Get-CimInstance Win32_Process -Filter "Name = 'pythonw.exe'" | Where-Object { $_.ExecutablePath -eq $runtimeExe -and $_.CommandLine -like "*app\start.py*" }) }
function Cleanup {
    AppProcesses | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    Get-Process -Name "PDF-Tool-Setup-*" -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2
    $uninstaller = Join-Path $target "unins000.exe"
    if (Test-Path $uninstaller) { Start-Process -FilePath $uninstaller -ArgumentList "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART" -Wait | Out-Null }
    Remove-Item $updates, $data -Recurse -Force -ErrorAction SilentlyContinue
}

if (Test-Path $target) { throw "PDF Tool ist auf diesem Rechner schon installiert" }

Write-Host "1. Vorversion installieren: $(Split-Path $Previous -Leaf)"
$log = Join-Path $temp "one-click-vorversion.log"
$run = Start-Process -FilePath $Previous -ArgumentList "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/LOG=`"$log`"" -Wait -PassThru
if ($run.ExitCode -ne 0) { throw "Installation der Vorversion fehlgeschlagen (Code $($run.ExitCode))" }
$installer = Join-Path $target "app\updater\installer.py"
if (-not (Select-String -Path $installer -Pattern "def helper_copy" -Quiet)) {
    Write-Host "   Vorversion startet den Hilfsprozess noch aus dem Programmordner (vor 4.0.0-beta.3) - Test entfaellt"
    Cleanup
    exit 0
}
try {
    $hidden = Start-Process -FilePath $launcher -ArgumentList "--hintergrund" -WorkingDirectory $target -PassThru
    $null = $hidden.Handle
    if (-not $hidden.WaitForExit(30000)) { throw "PDF-Tool.exe --hintergrund endete nicht" }
    $resident = $null
    for ($i = 0; $i -lt 30 -and -not $resident; $i++) { $resident = AppProcesses | Select-Object -First 1; if (-not $resident) { Start-Sleep -Seconds 1 } }
    if (-not $resident) { throw "Die Vorversion lief nach dem Start mit Windows nicht" }
    Start-Sleep -Seconds 10  # Oberflaeche fertig geladen, Dateien der Installation in Gebrauch
    Write-Host "   Vorversion laeuft im Hintergrund (Prozess $($resident.ProcessId))"

    Write-Host "2. Setup $version in den Update-Ordner legen"
    New-Item -ItemType Directory -Force -Path $updates | Out-Null
    $download = Join-Path $updates "PDF-Tool-Setup-$version.exe"
    Copy-Item $Setup $download -Force
    $sha = (Get-FileHash $download -Algorithm SHA256).Hash.ToLower()
    $startLog = Join-Path $updates "update-start.log"

    Write-Host "3. Updater-Code der Vorversion startet den Hilfsprozess, danach endet die App"
    $code = "import sys; from pathlib import Path; sys.path.insert(0, sys.argv[1]); from updater.installer import Launcher; Launcher().start(Path(sys.argv[2]), sys.argv[3], int(sys.argv[4]), Path(sys.argv[5]))"
    & (Join-Path $target "runtime\python.exe") -s -c $code (Join-Path $target "app") $download $sha $resident.ProcessId $startLog
    if ($LASTEXITCODE -ne 0) { throw "Hilfsprozess der Vorversion konnte nicht gestartet werden" }
    Stop-Process -Id $resident.ProcessId -Force

    Write-Host "4. Warten auf das stille Setup"
    $done = $null
    $watch = [Diagnostics.Stopwatch]::StartNew()
    while (-not $done -and $watch.Elapsed.TotalMinutes -lt 12) {
        if (Test-Path $startLog) { $done = Select-String -Path $startLog -Pattern "Update installiert|Stilles Setup endete|Stilles Setup nicht gestartet|Setup gestartet|Prüfung fehlgeschlagen|Setup läuft noch" | Select-Object -Last 1 }
        if (-not $done) { Start-Sleep -Seconds 2 }
    }
    Write-Host "   Protokoll des Hilfsprozesses:"
    if (Test-Path $startLog) { Get-Content $startLog -Encoding UTF8 | ForEach-Object { Write-Host "     $_" } }
    $setupLog = Join-Path $updates "update-setup.log"
    if (-not $done -or $done.Line -notlike "*Update installiert*") {
        if (Test-Path $setupLog) { Write-Host "   Ende des Setup-Protokolls:"; Get-Content $setupLog -Tail 60 | ForEach-Object { Write-Host "     $_" } }
        throw "Ein-Klick-Update: das stille Setup hat nicht installiert ($(if ($done) { $done.Line } else { 'Zeitlimit' }))"
    }
    Start-Sleep -Seconds 3
    $installed = (Get-ItemProperty -LiteralPath $appKey).DisplayVersion
    if ($installed -ne $version) { throw "Nach dem Update: App-Eintrag nennt $installed statt $version" }
    $restarted = $null
    for ($i = 0; $i -lt 40 -and -not $restarted; $i++) { $restarted = AppProcesses | Select-Object -First 1; if (-not $restarted) { Start-Sleep -Milliseconds 500 } }
    if (-not $restarted) { throw "PDF Tool wurde nach dem Update nicht neu gestartet" }
    Write-Host "   Still installiert: $version, PDF Tool neu gestartet (Prozess $($restarted.ProcessId))"
    if ($env:GITHUB_ACTIONS) { Write-Host "::notice title=Ein-Klick-Update::Vorversion im Hintergrund -> $version still installiert und neu gestartet" }
} finally {
    Write-Host "5. Aufraeumen"
    Cleanup
}
