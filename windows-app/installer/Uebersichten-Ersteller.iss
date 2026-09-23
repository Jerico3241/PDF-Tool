; ---------------------------------------------------------------------------
; Übersichten-Ersteller – Inno-Setup-Skript (Inno Setup 6.6 oder neuer)
;
; Bauen:   python windows-app/build.py
;          (bereitet build\payload vor und ruft ISCC.exe mit diesem Skript auf)
; Direkt:  ISCC.exe /DPayloadDir=<Ordner> windows-app\installer\Uebersichten-Ersteller.iss
;
; Installation pro Benutzer ohne Administratorrechte nach
;   %LOCALAPPDATA%\Uebersichten-Ersteller
; Benutzerdaten (Einstellungen, Vorlagen, Kundenverlauf) liegen getrennt unter
;   %APPDATA%\Uebersichten-Ersteller
; ---------------------------------------------------------------------------

#define AppName        "Übersichten-Ersteller"
#define AppFolder      "Uebersichten-Ersteller"
#define AppPublisher   "Jerico"
#define AppExeComment  "Vertragsübersichten aus Excel erstellen"
; Feste AppId – darf sich in künftigen Versionen NIE ändern, sonst entsteht eine zweite Installation.
#define AppId          "{{59C40061-D5E5-446D-ACB4-E077D3C71E1A}"
; Muss zu ui/windows.py passen (Taskleisten-Gruppierung und Erkennung der laufenden App)
#define AppUserModelID "Jerico.UebersichtenErsteller"
#define AppMutexName   "Jerico.UebersichtenErsteller.Instanz"
; Registrierung des alten, selbst geschriebenen Installers (bis 2.0.5)
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
AppMutex={#AppMutexName}
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
UsePreviousAppDir=yes
UsePreviousTasks=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0

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
OutputBaseFilename=Uebersichten-Ersteller-Setup-{#AppVersion}
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
de.LaunchApp=Übersichten-Ersteller starten
de.DesktopIcon=Verknüpfung auf dem &Desktop erstellen
de.ShortcutGroup=Verknüpfungen:
de.UpdateWelcome=Übersichten-Ersteller %1 wird auf Version {#AppVersion} aktualisiert.%n%nEinstellungen, Vorlagen, Textbausteine, Zyklus-Regeln und der Kundenverlauf bleiben erhalten.%n%nBitte schließen Sie die App, falls sie geöffnet ist. Klicken Sie dann auf »Weiter«.
de.RemoveUserData=Sollen auch Ihre gespeicherten Einstellungen, Vorlagen und der Kundenverlauf gelöscht werden?%n%nWählen Sie »Nein«, um sie für eine spätere Neuinstallation zu behalten. Erstellte PDF-Dateien werden in keinem Fall gelöscht.

[Tasks]
Name: "desktopicon"; Description: "{cm:DesktopIcon}"; GroupDescription: "{cm:ShortcutGroup}"

[InstallDelete]
; Programmordner werden vollständig ersetzt, damit keine Dateien älterer Laufzeiten übrig bleiben.
; Benutzerdaten liegen nicht hier (siehe [Code]: Übernahme der alten gui-config.json).
Type: filesandordirs; Name: "{app}\runtime"
Type: filesandordirs; Name: "{app}\app"
Type: filesandordirs; Name: "{app}\assets"
; Reste des selbst geschriebenen Installers bis 2.0.5
Type: files; Name: "{app}\Uebersichten-Ersteller.exe"
Type: files; Name: "{app}\Uebersichten-Ersteller.exe.alt"
Type: files; Name: "{app}\Deinstallieren.bat"
Type: files; Name: "{app}\Start.vbs"
Type: files; Name: "{app}\version.txt"
Type: files; Name: "{app}\start.log"
Type: filesandordirs; Name: "{app}\.alt-*"
Type: filesandordirs; Name: "{app}\.neu-*"
; Alte Verknüpfungen (2.0.x: Ordner im Startmenü) und frühere App-Namen
Type: filesandordirs; Name: "{userprograms}\Übersichten-Ersteller"
Type: filesandordirs; Name: "{userprograms}\UebersichtenErsteller"
Type: filesandordirs; Name: "{userprograms}\VertraView"
Type: filesandordirs; Name: "{userprograms}\Vertragsübersicht"
Type: filesandordirs; Name: "{userprograms}\VertragDesk"
Type: files; Name: "{userdesktop}\Übersichten-Ersteller.lnk"
Type: files; Name: "{userdesktop}\Uebersichten-Ersteller.lnk"
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

var
  LegacyVersion: String;

function LegacyInstallDir(): String;
begin
  if not RegQueryStringValue(HKCU, '{#LegacyUninstallKey}', 'InstallLocation', Result) then
    Result := '';
end;

function InitializeSetup(): Boolean;
begin
  LegacyVersion := '';
  if RegQueryStringValue(HKCU, '{#LegacyUninstallKey}', 'DisplayVersion', LegacyVersion) then
    Log('Vorhandene Installation des alten Installers: Version ' + LegacyVersion + ' in ' + LegacyInstallDir());
  Result := True;
end;

procedure InitializeWizard();
begin
  if LegacyVersion <> '' then
    WizardForm.WelcomeLabel2.Caption := FmtMessage(CustomMessage('UpdateWelcome'), [LegacyVersion]);
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  { Bei einer Aktualisierung der alten Version immer denselben Ordner verwenden: keine Parallelinstallation }
  Result := (PageID = wpSelectDir) and (LegacyVersion <> '') and (LegacyInstallDir() <> '');
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if (CurPageID = wpWelcome) and (LegacyVersion <> '') and (LegacyInstallDir() <> '') then
    WizardForm.DirEdit.Text := LegacyInstallDir();
end;

procedure MigrateUserData();
var
  Legacy, Target: String;
begin
  { Bis 2.0.5 lag gui-config.json im Programmordner. Sie wird in den Datenordner übernommen. }
  Legacy := ExpandConstant('{app}\gui-config.json');
  Target := ExpandConstant('{userappdata}\' + DataFolder + '\gui-config.json');
  if FileExists(Legacy) then
  begin
    if not FileExists(Target) then
    begin
      ForceDirectories(ExtractFileDir(Target));
      if FileCopy(Legacy, Target, True) then
        Log('Einstellungen übernommen: ' + Target)
      else
        Log('Einstellungen konnten nicht übernommen werden: ' + Legacy);
    end;
    if FileExists(Target) then
      RenameFile(Legacy, Legacy + '.2.0.5-sicherung');
  end;
  if FileExists(ExpandConstant('{app}\fehler.log')) then
    DeleteFile(ExpandConstant('{app}\fehler.log'));
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
  begin
    MigrateUserData();
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
  DataDir: String;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    DataDir := ExpandConstant('{userappdata}\' + DataFolder);
    DeleteFile(ExpandConstant('{app}\gui-config.json.2.0.5-sicherung'));
    RemoveDir(ExpandConstant('{app}'));
    if DirExists(DataDir) and not UninstallSilent() then
      if MsgBox(CustomMessage('RemoveUserData'), mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
        DelTree(DataDir, True, True, True);
  end;
end;
