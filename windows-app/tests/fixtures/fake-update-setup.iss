; Setup-Attrappe für den Updater-Test der CI (tests/smoke_updater.py): ein echtes Inno-Setup,
; das beim Start nur eine Markierung (mit seinen Parametern) schreibt – es installiert nichts. Still
; gestartet (»Jetzt installieren« seit 4.0: /SILENT …) endet es ohne Fenster mit Code 0; sichtbar
; gestartet endet es sofort (Code 1), damit die CI nicht auf einen Assistenten wartet.
; Die Datei für die Markierung kommt aus der Umgebungsvariablen PDFTOOL_E2E_MARKER (vererbt von
; der App über den Hilfsprozess an das Setup).
;
;   ISCC.exe /O<Ausgabeordner> fake-update-setup.iss   →  fake-update-setup.exe

[Setup]
AppName=PDF Tool Updater-Test
AppVersion=1.0
DefaultDirName={tmp}\pdf-tool-updater-test
CreateAppDir=no
Uninstallable=no
PrivilegesRequired=lowest
DisableWelcomePage=yes
OutputBaseFilename=fake-update-setup
SetupLogging=no

[Code]
function InitializeSetup(): Boolean;
var
  Marker: String;
begin
  Marker := GetEnv('PDFTOOL_E2E_MARKER');
  if Marker <> '' then
    SaveStringToFile(Marker, 'gestartet ' + GetCmdTail(), False);
  { Still: »installieren« (nichts) und mit Code 0 enden; sichtbar: ohne Assistent und ohne Meldung enden }
  Result := WizardSilent();
end;
