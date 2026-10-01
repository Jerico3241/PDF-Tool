; Setup-Attrappe für den Updater-Test der CI (tests/smoke_updater.py): ein echtes Inno-Setup,
; das beim Start nur eine Markierung schreibt und sofort endet – es installiert nichts.
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
    SaveStringToFile(Marker, 'gestartet', False);
  { Ende ohne Assistent und ohne Meldung }
  Result := False;
end;
