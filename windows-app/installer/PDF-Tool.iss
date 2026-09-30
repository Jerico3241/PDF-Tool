; ---------------------------------------------------------------------------
; PDF Tool – Inno-Setup-Skript (Inno Setup 6.6 oder neuer)
;
; Bauen:   python windows-app/build.py
;          (bereitet build\payload vor und ruft ISCC.exe mit diesem Skript auf)
; Direkt:  ISCC.exe /DPayloadDir=<Ordner> windows-app\installer\PDF-Tool.iss
;
; Installation pro Benutzer ohne Administratorrechte nach
;   %LOCALAPPDATA%\PDF-Tool
; Benutzerdaten (Einstellungen, Vorlagen, Kundenverlauf, Protokolle) liegen getrennt unter
;   %APPDATA%\PDF-Tool
;
; Bis Version 2.2 hieß die App »Übersichten-Ersteller« (Programmordner
; %LOCALAPPDATA%\Uebersichten-Ersteller, Daten %APPDATA%\Uebersichten-Ersteller).
; Ein Update verwendet dieselbe AppId – es entsteht kein zweiter Eintrag unter
; »Installierte Apps«. Die Programmdateien ziehen in den neuen Ordner um, der alte
; Programmordner wird danach entfernt (nur bekannte Programmdateien). Die
; Benutzerdaten übernimmt die App beim ersten Start mit Sicherung (appstate.py).
; ---------------------------------------------------------------------------

#define AppName        "PDF Tool"
#define AppFolder      "PDF-Tool"
#define AppPublisher   "Jerico"
#define AppExeComment  "Werkzeuge für PDF-Dateien: Vertragsübersichten erstellen, PDFs reparieren"
; Feste AppId – darf sich in künftigen Versionen NIE ändern, sonst entsteht eine zweite Installation.
#define AppGuid        "59C40061-D5E5-446D-ACB4-E077D3C71E1A"
#define AppId          "{{" + AppGuid + "}"
; Muss zu app/winsys.py passen (Taskleisten-Gruppierung und Erkennung der laufenden App)
#define AppUserModelID "Jerico.PDFTool"
#define AppMutexName   "Jerico.PDFTool.Instanz"
; Name, Ordner und Mutex bis Version 2.2 (»Übersichten-Ersteller«)
#define OldAppName     "Übersichten-Ersteller"
#define OldAppFolder   "Uebersichten-Ersteller"
#define OldMutexName   "Jerico.UebersichtenErsteller.Instanz"
; Registrierung dieses Setups (Inno Setup) und des alten, selbst geschriebenen Installers (bis 2.0.5)
#define UninstallKey       "Software\Microsoft\Windows\CurrentVersion\Uninstall\{" + AppGuid + "}_is1"
#define LegacyUninstallKey "Software\Microsoft\Windows\CurrentVersion\Uninstall\Uebersichten-Ersteller"

; Version zentral aus windows-app/VERSION
#ifndef AppVersion
  #define VersionHandle FileOpen(AddBackslash(SourcePath) + "..\VERSION")
  #define AppVersion Trim(FileRead(VersionHandle))
  #expr FileClose(VersionHandle)
#endif
#ifndef PayloadDir
  #define PayloadDir AddBackslash(SourcePath) + "..\build\payload"
#endif
#ifndef OutputDir
  #define OutputDir AddBackslash(SourcePath) + "..\dist"
#endif
#ifndef WizardDir
  #define WizardDir AddBackslash(SourcePath) + "..\build\wizard"
#endif

[Setup]
AppId={#AppId}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppCopyright=© {#AppPublisher}
AppComments={#AppExeComment}
; Auch die laufende Vorversion (Übersichten-Ersteller) wird erkannt
AppMutex={#AppMutexName},{#OldMutexName}
SetupMutex={#AppMutexName}.Setup
VersionInfoVersion={#AppVersion}.0
VersionInfoProductVersion={#AppVersion}
VersionInfoTextVersion={#AppVersion}
VersionInfoProductName={#AppName}
VersionInfoCompany={#AppPublisher}
VersionInfoDescription={#AppName} Setup
VersionInfoCopyright=© {#AppPublisher}

; Pro-Benutzer-Installation, keine Administratorrechte
PrivilegesRequired=lowest
DefaultDirName={localappdata}\{#AppFolder}
DisableDirPage=auto
DisableProgramGroupPage=yes
DisableReadyPage=yes
DisableWelcomePage=no
; Ein selbst gewählter Ordner bleibt; der alte Standardordner wird ersetzt (siehe [Code])
UsePreviousAppDir=yes
UsePreviousTasks=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; Qt 6 (Oberfläche seit 2.7.0) braucht Windows 10 Version 1809 (Build 17763) oder neuer – u. a. die
; mit Windows gelieferte ICU-Bibliothek. Ältere Systeme erhalten vom Setup einen Hinweis statt einer App,
; die nicht startet; eine vorhandene Installation bleibt dann unverändert.
MinVersion=10.0.17763

; Laufende App erkennen und zum Schließen auffordern (Restart Manager)
CloseApplications=yes
RestartApplications=no

; Erscheinungsbild: Windows-11-Stil, folgt Hell/Dunkel des Systems
WizardStyle=modern dynamic windows11
WizardSizePercent=100
SetupIconFile={#SourcePath}..\assets\icon.ico
#ifexist WizardDir + "\wizard-100.png"
WizardImageFile={#WizardDir}\wizard-100.png,{#WizardDir}\wizard-125.png,{#WizardDir}\wizard-150.png,{#WizardDir}\wizard-200.png
WizardSmallImageFile={#WizardDir}\small-100.png,{#WizardDir}\small-125.png,{#WizardDir}\small-150.png,{#WizardDir}\small-200.png
#endif

UninstallDisplayName={#AppName}
UninstallDisplayIcon={app}\assets\icon.ico
Uninstallable=yes

; Ausgabe
OutputDir={#OutputDir}
OutputBaseFilename=PDF-Tool-Setup-{#AppVersion}
Compression=lzma2/ultra64
SolidCompression=yes
LZMAUseSeparateProcess=yes
; Protokoll immer nach %TEMP%\Setup Log *.txt (zusätzlich /LOG="Datei" möglich)
SetupLogging=yes
ShowLanguageDialog=no
; Für eine spätere Signatur: SignTool=signtool $f  (siehe README.txt)

[Languages]
Name: "de"; MessagesFile: "compiler:Languages\German.isl"

[CustomMessages]
de.LaunchApp=PDF Tool starten
de.DesktopIcon=Verknüpfung auf dem &Desktop erstellen
de.ShortcutGroup=Verknüpfungen:
de.UpdateWelcome=PDF Tool %1 wird auf Version {#AppVersion} aktualisiert.%n%nEinstellungen, Kundenakten, Vertragsstände, Vorlagen, Textbausteine, Zyklus-Regeln und der gespeicherte Stapel bleiben erhalten.%n%nBitte schließen Sie die App, falls sie geöffnet ist. Klicken Sie dann auf »Weiter«.
de.RenameWelcome=Der {#OldAppName} %1 wird auf Version {#AppVersion} aktualisiert und heißt ab jetzt »PDF Tool«.%n%nNeu ist das Werkzeug »PDF reparieren«. Einstellungen, Vorlagen, Textbausteine, Zyklus-Regeln und der Kundenverlauf werden übernommen; vorher wird eine Sicherung angelegt.%n%nDie Verknüpfungen heißen danach »PDF Tool«. Bitte schließen Sie die App, falls sie geöffnet ist. Klicken Sie dann auf »Weiter«.
de.RemoveUserData=Sollen auch Ihre gespeicherten Einstellungen, Vorlagen, Kundenakten, Vertragsstände, der gespeicherte Stapel und die Protokolle gelöscht werden?%n%nWählen Sie »Nein«, um sie für eine spätere Neuinstallation zu behalten. Erstellte und reparierte PDF-Dateien sowie Ihre Excel-Listen werden in keinem Fall gelöscht.

[Tasks]
Name: "desktopicon"; Description: "{cm:DesktopIcon}"; GroupDescription: "{cm:ShortcutGroup}"

[InstallDelete]
; Programmordner werden vollständig ersetzt, damit keine Dateien älterer Laufzeiten übrig bleiben.
; Benutzerdaten liegen nicht hier.
Type: filesandordirs; Name: "{app}\runtime"
Type: filesandordirs; Name: "{app}\app"
Type: filesandordirs; Name: "{app}\assets"
; Reste des selbst geschriebenen Installers bis 2.0.5 (bei Installation im selben Ordner)
Type: files; Name: "{app}\Uebersichten-Ersteller.exe"
Type: files; Name: "{app}\Uebersichten-Ersteller.exe.alt"
Type: files; Name: "{app}\Deinstallieren.bat"
Type: files; Name: "{app}\Start.vbs"
Type: files; Name: "{app}\version.txt"
Type: files; Name: "{app}\start.log"
Type: filesandordirs; Name: "{app}\.alt-*"
Type: filesandordirs; Name: "{app}\.neu-*"
; Verknüpfungen des Übersichten-Erstellers (bis 2.2) und früherer App-Namen
Type: files; Name: "{userprograms}\Übersichten-Ersteller.lnk"
Type: files; Name: "{userdesktop}\Übersichten-Ersteller.lnk"
Type: files; Name: "{userdesktop}\Uebersichten-Ersteller.lnk"
Type: filesandordirs; Name: "{userprograms}\Übersichten-Ersteller"
Type: filesandordirs; Name: "{userprograms}\UebersichtenErsteller"
Type: filesandordirs; Name: "{userprograms}\VertraView"
Type: filesandordirs; Name: "{userprograms}\Vertragsübersicht"
Type: filesandordirs; Name: "{userprograms}\VertragDesk"
Type: files; Name: "{userdesktop}\VertraView.lnk"
Type: files; Name: "{userdesktop}\Vertragsübersicht.lnk"
Type: files; Name: "{userdesktop}\VertragDesk.lnk"
Type: filesandordirs; Name: "{localappdata}\VertraView"
Type: filesandordirs; Name: "{localappdata}\Vertragsübersicht"
Type: filesandordirs; Name: "{localappdata}\VertragDesk"

[Files]
Source: "{#PayloadDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
; pythonw.exe startet ohne Konsolenfenster
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\runtime\pythonw.exe"; Parameters: "-s -OO ""{app}\app\start.py"""; WorkingDir: "{app}\app"; IconFilename: "{app}\assets\icon.ico"; Comment: "{#AppExeComment}"; AppUserModelID: "{#AppUserModelID}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\runtime\pythonw.exe"; Parameters: "-s -OO ""{app}\app\start.py"""; WorkingDir: "{app}\app"; IconFilename: "{app}\assets\icon.ico"; Comment: "{#AppExeComment}"; AppUserModelID: "{#AppUserModelID}"; Tasks: desktopicon

[Run]
Filename: "{app}\runtime\pythonw.exe"; Parameters: "-s -OO ""{app}\app\start.py"""; WorkingDir: "{app}\app"; Description: "{cm:LaunchApp}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Zur Laufzeit entstandene Dateien im Programmordner
Type: filesandordirs; Name: "{app}\runtime"
Type: filesandordirs; Name: "{app}\app"
Type: filesandordirs; Name: "{app}\assets"
Type: files; Name: "{app}\fehler.log"
Type: files; Name: "{app}\start.log"
Type: dirifempty; Name: "{app}"

[Code]
const
  DataFolder = '{#AppFolder}';
  OldDataFolder = '{#OldAppFolder}';

var
  PreviousVersion: String;   { installierte Version (Inno Setup oder alter Installer) }
  PreviousName: String;      { angezeigter Name der installierten Version }
  PreviousDir: String;       { Programmordner der installierten Version }

function SamePath(A, B: String): Boolean;
begin
  Result := CompareText(RemoveBackslashUnlessRoot(A), RemoveBackslashUnlessRoot(B)) = 0;
end;

function OldDefaultDir(): String;
begin
  Result := ExpandConstant('{localappdata}\{#OldAppFolder}');
end;

function InitializeSetup(): Boolean;
begin
  PreviousVersion := '';
  PreviousName := '';
  PreviousDir := '';
  if RegQueryStringValue(HKCU, '{#UninstallKey}', 'Inno Setup: App Path', PreviousDir) then
  begin
    RegQueryStringValue(HKCU, '{#UninstallKey}', 'DisplayVersion', PreviousVersion);
    RegQueryStringValue(HKCU, '{#UninstallKey}', 'DisplayName', PreviousName);
    Log('Vorhandene Installation: ' + PreviousName + ' ' + PreviousVersion + ' in ' + PreviousDir);
  end
  else if RegQueryStringValue(HKCU, '{#LegacyUninstallKey}', 'DisplayVersion', PreviousVersion) then
  begin
    PreviousName := '{#OldAppName}';
    if not RegQueryStringValue(HKCU, '{#LegacyUninstallKey}', 'InstallLocation', PreviousDir) then
      PreviousDir := '';
    Log('Vorhandene Installation des alten Installers: Version ' + PreviousVersion + ' in ' + PreviousDir);
  end;
  Result := True;
end;

function RenamedUpdate(): Boolean;
begin
  Result := (PreviousVersion <> '') and (PreviousName <> '{#AppName}');
end;

procedure InitializeWizard();
begin
  if RenamedUpdate() then
    WizardForm.WelcomeLabel2.Caption := FmtMessage(CustomMessage('RenameWelcome'), [PreviousVersion])
  else if PreviousVersion <> '' then
    WizardForm.WelcomeLabel2.Caption := FmtMessage(CustomMessage('UpdateWelcome'), [PreviousVersion]);
  { Der alte Standardordner (…\Uebersichten-Ersteller) wird durch den neuen ersetzt.
    Ein selbst gewählter Ordner bleibt erhalten. Gilt auch für stille Installationen. }
  if (PreviousDir <> '') and SamePath(PreviousDir, OldDefaultDir()) then
    WizardForm.DirEdit.Text := ExpandConstant('{localappdata}\' + DataFolder);
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  { Bei einem Update keinen Ordner abfragen: keine Parallelinstallation }
  Result := (PageID = wpSelectDir) and (PreviousVersion <> '');
end;

function LooksLikeOurProgramDir(Dir: String): Boolean;
begin
  { Nur ein Ordner mit den bekannten Programmdateien wird angefasst. }
  Result := (Dir <> '') and DirExists(Dir) and (Length(RemoveBackslashUnlessRoot(Dir)) > 3) and
    (FileExists(Dir + '\app\start.py') or FileExists(Dir + '\app\vertragdesk.py') or
     FileExists(Dir + '\Uebersichten-Ersteller.exe') or FileExists(Dir + '\Start.vbs'));
end;

procedure DeleteKnownFile(Dir, Name: String);
begin
  if FileExists(Dir + '\' + Name) then
    if not DeleteFile(Dir + '\' + Name) then
      Log('Konnte nicht entfernt werden: ' + Dir + '\' + Name);
end;

procedure DeleteKnownDir(Dir, Name: String);
begin
  if DirExists(Dir + '\' + Name) then
    if not DelTree(Dir + '\' + Name, True, True, True) then
      Log('Ordner konnte nicht entfernt werden: ' + Dir + '\' + Name);
end;

procedure KeepFile(Source, TargetDir: String);
var
  Target: String;
begin
  { Datei aus dem alten Programmordner in den Datenordner verschieben (nie überschreiben). }
  if not FileExists(Source) then
    exit;
  Target := TargetDir + '\' + ExtractFileName(Source);
  ForceDirectories(TargetDir);
  if FileExists(Target) then
    Target := Target + '.alt';
  if FileExists(Target) then
    exit;
  if FileCopy(Source, Target, True) then
  begin
    Log('Übernommen: ' + Source + ' -> ' + Target);
    DeleteFile(Source);
  end
  else
    Log('Konnte nicht übernommen werden: ' + Source);
end;

procedure MigrateLegacyConfig(Dir: String);
var
  Config, OldData, NewData: String;
begin
  { Bis 2.0.5 lag gui-config.json im Programmordner. Sie kommt in den Datenordner der
    Vorversion; von dort übernimmt die App beim ersten Start alle Daten mit Sicherung. }
  Config := Dir + '\gui-config.json';
  if not FileExists(Config) then
    exit;
  OldData := ExpandConstant('{userappdata}\' + OldDataFolder);
  NewData := ExpandConstant('{userappdata}\' + DataFolder);
  if not FileExists(OldData + '\gui-config.json') and not FileExists(NewData + '\gui-config.json') then
  begin
    ForceDirectories(OldData);
    if FileCopy(Config, OldData + '\gui-config.json', True) then
      Log('Einstellungen (bis 2.0.5) übernommen: ' + OldData)
    else
    begin
      Log('Einstellungen (bis 2.0.5) konnten nicht übernommen werden – der alte Ordner bleibt.');
      exit;
    end;
  end;
  if RenameFile(Config, Config + '.2.0.5-sicherung') then
    Log('Alte Einstellungsdatei gesichert: ' + Config + '.2.0.5-sicherung');
end;

procedure RemoveOldProgramDir();
var
  Dir: String;
begin
  Dir := RemoveBackslashUnlessRoot(PreviousDir);
  if (Dir = '') or SamePath(Dir, ExpandConstant('{app}')) then
    exit;
  if not LooksLikeOurProgramDir(Dir) then
  begin
    Log('Alter Programmordner wird nicht verändert (unbekannter Inhalt): ' + Dir);
    exit;
  end;
  Log('Alter Programmordner wird aufgeräumt: ' + Dir);
  MigrateLegacyConfig(Dir);
  { Sicherungen der Einstellungen bleiben erhalten – im Datenordner }
  KeepFile(Dir + '\gui-config.json.2.0.5-sicherung', ExpandConstant('{userappdata}\' + DataFolder));
  DeleteKnownDir(Dir, 'runtime');
  DeleteKnownDir(Dir, 'app');
  DeleteKnownDir(Dir, 'assets');
  DeleteKnownFile(Dir, 'VERSION');
  DeleteKnownFile(Dir, 'README.txt');
  DeleteKnownFile(Dir, 'fehler.log');
  DeleteKnownFile(Dir, 'start.log');
  DeleteKnownFile(Dir, 'unins000.exe');
  DeleteKnownFile(Dir, 'unins000.dat');
  DeleteKnownFile(Dir, 'unins000.msg');
  { Reste des selbst geschriebenen Installers bis 2.0.5 }
  DeleteKnownFile(Dir, 'Uebersichten-Ersteller.exe');
  DeleteKnownFile(Dir, 'Uebersichten-Ersteller.exe.alt');
  DeleteKnownFile(Dir, 'Deinstallieren.bat');
  DeleteKnownFile(Dir, 'Start.vbs');
  DeleteKnownFile(Dir, 'version.txt');
  DelTree(Dir + '\.alt-*', False, True, True);
  DelTree(Dir + '\.neu-*', False, True, True);
  { Nur ein leerer Ordner wird entfernt – unbekannte Dateien bleiben unangetastet. }
  if RemoveDir(Dir) then
    Log('Alter Programmordner entfernt: ' + Dir)
  else
    Log('Alter Programmordner enthält weitere Dateien und bleibt bestehen: ' + Dir);
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
  begin
    { Gleicher Ordner (z. B. selbst gewählt oder Update bis 2.0.5 im selben Ordner): alte Einstellungsdatei übernehmen }
    if SamePath(PreviousDir, ExpandConstant('{app}')) then
      MigrateLegacyConfig(ExpandConstant('{app}'))
    else
      RemoveOldProgramDir();
    { Eintrag des alten Installers entfernen, sonst stünde die App zweimal unter „Installierte Apps“ }
    if RegKeyExists(HKCU, '{#LegacyUninstallKey}') then
    begin
      RegDeleteKeyIncludingSubkeys(HKCU, '{#LegacyUninstallKey}');
      Log('Alter Deinstallationseintrag entfernt');
    end;
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  DataDir, OldDataDir: String;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    DataDir := ExpandConstant('{userappdata}\' + DataFolder);
    OldDataDir := ExpandConstant('{userappdata}\' + OldDataFolder);
    DeleteFile(ExpandConstant('{app}\gui-config.json.2.0.5-sicherung'));
    RemoveDir(ExpandConstant('{app}'));
    if (DirExists(DataDir) or DirExists(OldDataDir)) and not UninstallSilent() then
      if MsgBox(CustomMessage('RemoveUserData'), mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
      begin
        { Auch die bei der Übernahme unverändert gebliebenen Daten des Übersichten-Erstellers }
        DelTree(DataDir, True, True, True);
        DelTree(OldDataDir, True, True, True);
      end;
  end;
end;
