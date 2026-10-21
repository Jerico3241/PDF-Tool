# Startzeit unter Windows: installiertes PDF Tool der Vorversion und der neuen Version im Vergleich.
#
#   ./windows-app/tests/bench_windows.ps1 -Setup <neues Setup> -Previous <Setup der Vorversion> [-Runs 7]
#
# Beide Setups werden nacheinander still installiert, mit der eigenen Laufzeit des Programms gemessen
# (tests/bench_app.py: Programmstart bis zur Startseite, echtes Fenster mit der Windows-Plattform) und wieder
# deinstalliert. Gemessen wird auf demselben Rechner im selben Lauf – nur so sind die Werte vergleichbar.
# Die Tabellen gehen in die Zusammenfassung des Laufs. Kein Test: die Messung bricht den Lauf nicht ab,
# solange sie Ergebnisse liefert. Einstellungen und Daten der Messung sind eigene (UE_CONFIG_FILE, UE_DATA_DIR).
param(
    [Parameter(Mandatory = $true)][string]$Setup,
    [Parameter(Mandatory = $true)][string]$Previous,
    [int]$Runs = 7
)
$ErrorActionPreference = "Stop"
trap {
    # Fehler als Meldung am Lauf (die Protokolle sind nicht immer zugänglich)
    $text = ($_.Exception.Message + " " + $_.InvocationInfo.PositionMessage) -replace "[\r\n]+", " "
    Write-Host "::warning title=Startzeit-Messung fehlgeschlagen::$text"
    exit 1
}
$target = Join-Path $env:LOCALAPPDATA "PDF-Tool"
$bench = Join-Path $PSScriptRoot "bench_app.py"
$out = Join-Path $env:RUNNER_TEMP "startzeit"
New-Item -ItemType Directory -Force -Path $out | Out-Null
if (Test-Path $target) { throw "PDF Tool ist schon installiert ($target) – die Messung braucht einen leeren Rechner" }

function Measure-Setup([string]$file, [string]$name) {
    $log = Join-Path $out "setup-$name.log"
    $run = Start-Process -FilePath $file -ArgumentList "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/LOG=`"$log`"" -Wait -PassThru
    if ($run.ExitCode -ne 0) { throw "Installation ($name) fehlgeschlagen (Code $($run.ExitCode))" }
    $version = (Get-Content (Join-Path $target "VERSION") -Raw).Trim()
    try {
        $env:QT_QPA_PLATFORM = "windows"
        # Jeder Teil für sich: scheitert einer, bleiben die anderen Werte erhalten
        foreach ($scenario in "start") {  # »reader« und »oeffnen_mit« laufen auf den CI-Rechnern nicht zuverlässig durch
            $errors = Join-Path $out "$name-$scenario.err"
            & (Join-Path $target "runtime\python.exe") -s $bench $scenario --runs $Runs --app (Join-Path $target "app") --label $version --json (Join-Path $out "$name-$scenario.json") 2> $errors | Tee-Object -FilePath (Join-Path $out "$name.md") -Append | Out-Host
            if ($LASTEXITCODE -ne 0) {
                $text = ((Get-Content $errors -Raw -ErrorAction SilentlyContinue) -replace "[\r\n]+", " ")
                if ($text.Length -gt 800) { $text = $text.Substring($text.Length - 800) }
                Write-Host "::warning title=Startzeit-Messung ($version, $scenario)::$text"
            }
        }
    } finally {
        Remove-Item Env:QT_QPA_PLATFORM -ErrorAction SilentlyContinue
        $uninstall = Start-Process -FilePath (Join-Path $target "unins000.exe") -ArgumentList "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART" -Wait -PassThru
        if ($uninstall.ExitCode -ne 0) { throw "Deinstallation ($name) fehlgeschlagen" }
        for ($i = 0; $i -lt 30 -and (Test-Path (Join-Path $target "runtime")); $i++) { Start-Sleep -Milliseconds 500 }
    }
    return $version
}

$old = Measure-Setup $Previous "vorversion"
$new = Measure-Setup $Setup "neu"

# Vergleich der Mediane: Zusammenfassung des Laufs und eine Meldung am Lauf
$env:PYTHONIOENCODING = "utf-8"
$compare = & python (Join-Path $PSScriptRoot "bench_compare.py") (Join-Path $out "vorversion") (Join-Path $out "neu")
if ($LASTEXITCODE -ne 0) { throw "Vergleich fehlgeschlagen" }
$brief = ($compare | Where-Object { $_ -like "BRIEF *" }) -replace "^BRIEF ", ""
$table = $compare | Where-Object { $_ -notlike "BRIEF *" }
Write-Host "::notice title=Startzeit unter Windows ($old -> $new)::$brief"
if ($env:GITHUB_STEP_SUMMARY) {
    @("### Startzeit unter Windows: PDF Tool $old → $new", "", "Installiertes Programm, je $Runs Starts, Median.", "") + $table + @("", "<details><summary>Einzelwerte</summary>", "") + (Get-Content (Join-Path $out "vorversion.md")) + @("") + (Get-Content (Join-Path $out "neu.md")) + @("", "</details>") |
        Out-File -FilePath $env:GITHUB_STEP_SUMMARY -Append -Encoding utf8
}
