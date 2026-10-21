; ---------------------------------------------------------------------------
; Novadesk – Inno-Setup-Skript (Inno Setup 6.6 oder neuer)
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

; Seit 5.0 heißt die App »Novadesk« (bis 4.0 »PDF Tool«). Ordner, AppId, ProgID, AppUserModelID, Mutex und der
; Name der EXE bleiben bewusst, wie sie waren: So ersetzt ein Update die Installation von PDF Tool, statt eine
; zweite anzulegen, und Daten, Einstellungen und »Öffnen mit« bleiben erhalten.
#define AppName        "Novadesk"
#define PdfToolName    "PDF Tool"
#define AppFolder      "PDF-Tool"
#define AppPublisher   "Jerico"
#define AppExeComment  "Office für Windows: Tabellen, Texte, Präsentationen und PDFs ansehen, PDFs bearbeiten, Vertragsübersichten erstellen"
; Feste AppId – darf sich in künftigen Versionen NIE ändern, sonst entsteht eine zweite Installation.
#define AppGuid        "59C40061-D5E5-446D-ACB4-E077D3C71E1A"
#define AppId          "{{" + AppGuid + "}"
; Muss zu app/winsys.py passen (Taskleisten-Gruppierung und Erkennung der laufenden App)
#define AppUserModelID "Jerico.PDFTool"
#define AppMutexName   "Jerico.PDFTool.Instanz"
; »Öffnen mit« für PDF-Dateien (seit 3.0.0): eigene ProgID, nur für diesen Benutzer
#define PdfProgId      "PDFTool.Dokument"
; Startprogramm mit Symbol und Namen von PDF Tool (seit 3.2.0-beta.3, installer/launcher): startet
; runtime\pythonw.exe -s -OO app\start.py – Windows zeigt sonst in »Öffnen mit« und bei den Standard-Apps Python
#define AppExe         "PDF-Tool.exe"
; Öffnen über die Dateizuordnung (seit 4.0.0-beta.4): DelegateExecute – Windows startet PDF-Tool.exe als COM-Server
; (IExecuteCommand), nicht als Kindprozess des Aufrufers. Muss zu CLSID_PDFTOOL_OPEN in installer/launcher/launcher.c passen.
; Symbol der PDF-Dateien und in »Öffnen mit«: eigene Symbol-Ressource von PDF-Tool.exe. Windows merkt sich Symbole
; nach Datei und Nummer – mit derselben Nummer bliebe nach einem neuen Symbol das alte sichtbar (Sprungliste,
; Explorer). Bei einem neuen Symbol die Nummer erhöhen (installer/launcher/launcher.rc). Seit 5.0 (Novadesk):
; App-Symbol -3, je Dateiart ein eigenes Symbol (-10 PDF, -11 Text, -12 Tabelle, -13 Präsentation, -14 CSV).
#define AppIcon        "-3"
#define DocIcon        "-10"
#define TextIcon       "-11"
#define SheetIcon      "-12"
#define SlidesIcon     "-13"
#define CsvIcon        "-14"
; »Öffnen mit« für Office-Dateien (seit 5.0): je Dateiart eine ProgID mit eigenem Symbol, nur für diesen Benutzer.
; Novadesk wird dabei nicht zur Standard-App – das wählt nur der Benutzer.
#define TextProgId     "Novadesk.Text"
#define SheetProgId    "Novadesk.Tabelle"
#define SlidesProgId   "Novadesk.Praesentation"
#define CsvProgId      "Novadesk.Csv"
#define OpenClsid      "{{61E62B6E-0FE6-46A2-8AF1-BD670901BF3B}"
; Anmeldung als Programm für PDF-Dateien (Einstellungen → Apps → Standard-Apps), nur für diesen Benutzer
#define CapabilitiesKey "Software\PDF-Tool\Capabilities"
#define RunKey         "Software\Microsoft\Windows\CurrentVersion\Run"
; Name, Ordner und Mutex bis Version 2.2 (»Übersichten-Ersteller«)
#define OldAppName     "Übersichten-Ersteller"
#define OldAppFolder   "Uebersichten-Ersteller"
#define OldMutexName   "Jerico.UebersichtenErsteller.Instanz"
; Registrierung dieses Setups (Inno Setup) und des alten, selbst geschriebenen Installers (bis 2.0.5)
#define UninstallKey       "Software\Microsoft\Windows\CurrentVersion\Uninstall\{" + AppGuid + "}_is1"
#define LegacyUninstallKey "Software\Microsoft\Windows\CurrentVersion\Uninstall\Uebersichten-Ersteller"

; Version zentral aus windows-app/VERSION – stabil »2.7.2« oder Beta »2.8.0-beta.1«
#ifndef AppVersion
  #define VersionHandle FileOpen(AddBackslash(SourcePath) + "..\VERSION")
  #define AppVersion Trim(FileRead(VersionHandle))
  #expr FileClose(VersionHandle)
#endif
; Windows-Dateiversionen bestehen nur aus Zahlen: bei einer Beta der Teil vor »-« (2.8.0-beta.1 → 2.8.0)
#ifndef AppNumericVersion
  #if Pos("-", AppVersion) > 0
    #define AppNumericVersion Copy(AppVersion, 1, Pos("-", AppVersion) - 1)
  #else
    #define AppNumericVersion AppVersion
  #endif
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
VersionInfoVersion={#AppNumericVersion}.0
VersionInfoProductVersion={#AppNumericVersion}
VersionInfoTextVersion={#AppVersion}
VersionInfoProductTextVersion={#AppVersion}
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

; »Öffnen mit« (siehe [Registry]): Explorer nach der Installation benachrichtigen
ChangesAssociations=yes

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
de.LaunchApp=Novadesk starten
de.DesktopIcon=Verknüpfung auf dem &Desktop erstellen
de.ShortcutGroup=Verknüpfungen:
de.UpdateWelcome=Novadesk %1 wird auf Version {#AppVersion} aktualisiert.%n%nEinstellungen, Kundenakten, Vertragsstände, Vorlagen, Textbausteine, Zyklus-Regeln und der gespeicherte Stapel bleiben erhalten.%n%nBitte schließen Sie die App, falls sie geöffnet ist. Klicken Sie dann auf »Weiter«.
de.RenameWelcome=Der {#OldAppName} %1 wird auf Version {#AppVersion} aktualisiert und heißt ab jetzt »Novadesk«.%n%nNeu ist das Werkzeug »PDF reparieren«. Einstellungen, Vorlagen, Textbausteine, Zyklus-Regeln und der Kundenverlauf werden übernommen; vorher wird eine Sicherung angelegt.%n%nDie Verknüpfungen heißen danach »Novadesk«. Bitte schließen Sie die App, falls sie geöffnet ist. Klicken Sie dann auf »Weiter«.
de.NovadeskWelcome=PDF Tool %1 wird auf Version {#AppVersion} aktualisiert und heißt ab jetzt »Novadesk«.%n%nNeu: Word-, Excel- und PowerPoint-Dateien öffnen sich direkt zum Ansehen, dazu eine neue Startseite und neue Symbole für jede Dateiart. Alle PDF-Werkzeuge, Einstellungen, Kundenakten, Vertragsstände und Vorlagen bleiben erhalten.%n%nDie Verknüpfungen heißen danach »Novadesk«. Bitte schließen Sie die App, falls sie geöffnet ist. Klicken Sie dann auf »Weiter«.
de.RemoveUserData=Sollen auch Ihre gespeicherten Einstellungen, Vorlagen, Regelwerke, Kundenakten, Vertragsstände, der gespeicherte Stapel, die automatischen Sicherungen im Datenordner und die Protokolle gelöscht werden?%n%nWählen Sie »Nein«, um sie für eine spätere Neuinstallation zu behalten. Erstellte und reparierte PDF-Dateien, Ihre Excel-Listen und Sicherungen außerhalb des Datenordners werden in keinem Fall gelöscht.

[Tasks]
Name: "desktopicon"; Description: "{cm:DesktopIcon}"; GroupDescription: "{cm:ShortcutGroup}"

[InstallDelete]
; Programmordner werden vollständig ersetzt, damit keine Dateien älterer Laufzeiten übrig bleiben.
; Benutzerdaten liegen nicht hier.
Type: filesandordirs; Name: "{app}\runtime"
Type: filesandordirs; Name: "{app}\app"
Type: filesandordirs; Name: "{app}\assets"
; Texterkennung (Tesseract): DLLs einer älteren Tesseract-Version bleiben so nicht liegen
Type: filesandordirs; Name: "{app}\ocr"
; KI-Laufzeit (llama.cpp): ebenso – Sprachmodelle liegen nicht hier, sondern in {localappdata}\PDF-Tool-KI
Type: filesandordirs; Name: "{app}\ai"
; LibreOffice (seit 5.0): ebenso – nie Dateien einer älteren LibreOffice-Version mischen
Type: filesandordirs; Name: "{app}\office"
; Reste des selbst geschriebenen Installers bis 2.0.5 (bei Installation im selben Ordner)
Type: files; Name: "{app}\Uebersichten-Ersteller.exe"
Type: files; Name: "{app}\Uebersichten-Ersteller.exe.alt"
Type: files; Name: "{app}\Deinstallieren.bat"
Type: files; Name: "{app}\Start.vbs"
Type: files; Name: "{app}\version.txt"
Type: files; Name: "{app}\start.log"
Type: filesandordirs; Name: "{app}\.alt-*"
Type: filesandordirs; Name: "{app}\.neu-*"
; Verknüpfungen von PDF Tool (bis 4.0) – sie heißen jetzt »Novadesk«
Type: files; Name: "{userprograms}\{#PdfToolName}.lnk"
Type: files; Name: "{userdesktop}\{#PdfToolName}.lnk"
Type: files; Name: "{usersendto}\{#PdfToolName} (Bilder zu PDF).lnk"
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
; Das ganze Paket aus build.py – darunter LICENSE (GPL-3.0) und THIRD_PARTY_LICENSES.md im Programmordner.
; Bewusst keine Lizenzseite (LicenseFile) im Assistenten: Die GPL verlangt keine Zustimmung.
Source: "{#PayloadDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
; PDF-Tool.exe startet pythonw.exe ohne Konsolenfenster (Symbol und Name von PDF Tool)
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"; WorkingDir: "{app}"; IconFilename: "{app}\{#AppExe}"; Comment: "{#AppExeComment}"; AppUserModelID: "{#AppUserModelID}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; WorkingDir: "{app}"; IconFilename: "{app}\{#AppExe}"; Comment: "{#AppExeComment}"; AppUserModelID: "{#AppUserModelID}"; Tasks: desktopicon
; Explorer: Bilder markieren → Rechtsklick → »Senden an« → »PDF Tool (Bilder zu PDF)« – PDF Tool fügt sie zu einer PDF
; zusammen (läuft es schon, übernimmt die laufende App die Bilder). Die Deinstallation entfernt die Verknüpfung.
Name: "{usersendto}\{#AppName} (Bilder zu PDF)"; Filename: "{app}\{#AppExe}"; WorkingDir: "{app}"; IconFilename: "{app}\{#AppExe}"; Comment: "Bilder zu einer PDF zusammenfügen"

[Registry]
; »Öffnen mit« → »PDF Tool« für PDF-Dateien (HKCU, keine Administratorrechte). PDF Tool wird dabei NICHT
; zur Standard-App: Die bisherige Zuordnung von .pdf bleibt unverändert; der Eintrag erscheint in der
; Liste »Öffnen mit« und unter Einstellungen → Apps → Standard-Apps – auswählen kann ihn nur der Benutzer.
; Die Deinstallation entfernt genau diese Einträge.
Root: HKCU; Subkey: "Software\Classes\{#PdfProgId}"; ValueType: string; ValueName: ""; ValueData: "PDF-Dokument"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\{#PdfProgId}"; ValueType: string; ValueName: "FriendlyTypeName"; ValueData: "PDF-Dokument"
Root: HKCU; Subkey: "Software\Classes\{#PdfProgId}"; ValueType: string; ValueName: "AppUserModelID"; ValueData: "{#AppUserModelID}"
Root: HKCU; Subkey: "Software\Classes\{#PdfProgId}\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"",{#DocIcon}"
Root: HKCU; Subkey: "Software\Classes\{#PdfProgId}\shell\open"; ValueType: string; ValueName: "FriendlyAppName"; ValueData: "{#AppName}"
Root: HKCU; Subkey: "Software\Classes\{#PdfProgId}\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" ""%1"""
Root: HKCU; Subkey: "Software\Classes\{#PdfProgId}\shell\open\command"; ValueType: string; ValueName: "DelegateExecute"; ValueData: "{#OpenClsid}"
; COM-Klasse dazu (nur dieser Benutzer): Windows startet "PDF-Tool.exe" -Embedding und übergibt die Dateien
Root: HKCU; Subkey: "Software\Classes\CLSID\{#OpenClsid}"; ValueType: string; ValueName: ""; ValueData: "{#AppName} – Öffnen"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\CLSID\{#OpenClsid}\LocalServer32"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"""
; Das Programm selbst: Name und Symbol in »Öffnen mit« (Windows liest sie sonst aus der EXE)
Root: HKCU; Subkey: "Software\Classes\Applications\{#AppExe}"; ValueType: string; ValueName: "FriendlyAppName"; ValueData: "{#AppName}"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\Applications\{#AppExe}\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"",{#AppIcon}"
Root: HKCU; Subkey: "Software\Classes\Applications\{#AppExe}\SupportedTypes"; ValueType: string; ValueName: ".pdf"; ValueData: ""
Root: HKCU; Subkey: "Software\Classes\Applications\{#AppExe}\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" ""%1"""
Root: HKCU; Subkey: "Software\Classes\Applications\{#AppExe}\shell\open\command"; ValueType: string; ValueName: "DelegateExecute"; ValueData: "{#OpenClsid}"
; Standard-Apps: PDF Tool als Programm für .pdf anmelden (Capabilities + RegisteredApplications)
Root: HKCU; Subkey: "{#CapabilitiesKey}"; ValueType: string; ValueName: "ApplicationName"; ValueData: "{#AppName}"; Flags: uninsdeletekey
Root: HKCU; Subkey: "{#CapabilitiesKey}"; ValueType: string; ValueName: "ApplicationDescription"; ValueData: "{#AppExeComment}"
Root: HKCU; Subkey: "{#CapabilitiesKey}"; ValueType: string; ValueName: "ApplicationIcon"; ValueData: """{app}\{#AppExe}"",{#AppIcon}"
Root: HKCU; Subkey: "{#CapabilitiesKey}\FileAssociations"; ValueType: string; ValueName: ".pdf"; ValueData: "{#PdfProgId}"
Root: HKCU; Subkey: "Software\PDF-Tool"; Flags: uninsdeletekeyifempty
Root: HKCU; Subkey: "Software\RegisteredApplications"; ValueType: string; ValueName: "{#AppName}"; ValueData: "{#CapabilitiesKey}"; Flags: uninsdeletevalue
; .pdf und .pdf\OpenWithProgids nur entfernen, wenn sie danach leer sind (Einträge anderer Programme bleiben)
Root: HKCU; Subkey: "Software\Classes\.pdf"; Flags: uninsdeletekeyifempty
Root: HKCU; Subkey: "Software\Classes\.pdf\OpenWithProgids"; ValueType: string; ValueName: "{#PdfProgId}"; ValueData: ""; Flags: uninsdeletevalue uninsdeletekeyifempty

; Office-Dateien (seit 5.0): dieselben Einträge wie für PDF – je Dateiart eine ProgID mit eigenem Symbol
Root: HKCU; Subkey: "Software\Classes\{#TextProgId}"; ValueType: string; ValueName: ""; ValueData: "Text-Dokument"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\{#TextProgId}"; ValueType: string; ValueName: "FriendlyTypeName"; ValueData: "Text-Dokument"
Root: HKCU; Subkey: "Software\Classes\{#TextProgId}"; ValueType: string; ValueName: "AppUserModelID"; ValueData: "{#AppUserModelID}"
Root: HKCU; Subkey: "Software\Classes\{#TextProgId}\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"",{#TextIcon}"
Root: HKCU; Subkey: "Software\Classes\{#TextProgId}\shell\open"; ValueType: string; ValueName: "FriendlyAppName"; ValueData: "{#AppName}"
Root: HKCU; Subkey: "Software\Classes\{#TextProgId}\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" ""%1"""
Root: HKCU; Subkey: "Software\Classes\{#TextProgId}\shell\open\command"; ValueType: string; ValueName: "DelegateExecute"; ValueData: "{#OpenClsid}"
Root: HKCU; Subkey: "Software\Classes\Applications\{#AppExe}\SupportedTypes"; ValueType: string; ValueName: ".docx"; ValueData: ""
Root: HKCU; Subkey: "{#CapabilitiesKey}\FileAssociations"; ValueType: string; ValueName: ".docx"; ValueData: "{#TextProgId}"
Root: HKCU; Subkey: "Software\Classes\.docx"; Flags: uninsdeletekeyifempty
Root: HKCU; Subkey: "Software\Classes\.docx\OpenWithProgids"; ValueType: string; ValueName: "{#TextProgId}"; ValueData: ""; Flags: uninsdeletevalue uninsdeletekeyifempty
Root: HKCU; Subkey: "Software\Classes\Applications\{#AppExe}\SupportedTypes"; ValueType: string; ValueName: ".doc"; ValueData: ""
Root: HKCU; Subkey: "{#CapabilitiesKey}\FileAssociations"; ValueType: string; ValueName: ".doc"; ValueData: "{#TextProgId}"
Root: HKCU; Subkey: "Software\Classes\.doc"; Flags: uninsdeletekeyifempty
Root: HKCU; Subkey: "Software\Classes\.doc\OpenWithProgids"; ValueType: string; ValueName: "{#TextProgId}"; ValueData: ""; Flags: uninsdeletevalue uninsdeletekeyifempty
Root: HKCU; Subkey: "Software\Classes\Applications\{#AppExe}\SupportedTypes"; ValueType: string; ValueName: ".docm"; ValueData: ""
Root: HKCU; Subkey: "{#CapabilitiesKey}\FileAssociations"; ValueType: string; ValueName: ".docm"; ValueData: "{#TextProgId}"
Root: HKCU; Subkey: "Software\Classes\.docm"; Flags: uninsdeletekeyifempty
Root: HKCU; Subkey: "Software\Classes\.docm\OpenWithProgids"; ValueType: string; ValueName: "{#TextProgId}"; ValueData: ""; Flags: uninsdeletevalue uninsdeletekeyifempty
Root: HKCU; Subkey: "Software\Classes\Applications\{#AppExe}\SupportedTypes"; ValueType: string; ValueName: ".odt"; ValueData: ""
Root: HKCU; Subkey: "{#CapabilitiesKey}\FileAssociations"; ValueType: string; ValueName: ".odt"; ValueData: "{#TextProgId}"
Root: HKCU; Subkey: "Software\Classes\.odt"; Flags: uninsdeletekeyifempty
Root: HKCU; Subkey: "Software\Classes\.odt\OpenWithProgids"; ValueType: string; ValueName: "{#TextProgId}"; ValueData: ""; Flags: uninsdeletevalue uninsdeletekeyifempty
Root: HKCU; Subkey: "Software\Classes\Applications\{#AppExe}\SupportedTypes"; ValueType: string; ValueName: ".rtf"; ValueData: ""
Root: HKCU; Subkey: "{#CapabilitiesKey}\FileAssociations"; ValueType: string; ValueName: ".rtf"; ValueData: "{#TextProgId}"
Root: HKCU; Subkey: "Software\Classes\.rtf"; Flags: uninsdeletekeyifempty
Root: HKCU; Subkey: "Software\Classes\.rtf\OpenWithProgids"; ValueType: string; ValueName: "{#TextProgId}"; ValueData: ""; Flags: uninsdeletevalue uninsdeletekeyifempty
Root: HKCU; Subkey: "Software\Classes\{#SheetProgId}"; ValueType: string; ValueName: ""; ValueData: "Tabelle"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\{#SheetProgId}"; ValueType: string; ValueName: "FriendlyTypeName"; ValueData: "Tabelle"
Root: HKCU; Subkey: "Software\Classes\{#SheetProgId}"; ValueType: string; ValueName: "AppUserModelID"; ValueData: "{#AppUserModelID}"
Root: HKCU; Subkey: "Software\Classes\{#SheetProgId}\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"",{#SheetIcon}"
Root: HKCU; Subkey: "Software\Classes\{#SheetProgId}\shell\open"; ValueType: string; ValueName: "FriendlyAppName"; ValueData: "{#AppName}"
Root: HKCU; Subkey: "Software\Classes\{#SheetProgId}\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" ""%1"""
Root: HKCU; Subkey: "Software\Classes\{#SheetProgId}\shell\open\command"; ValueType: string; ValueName: "DelegateExecute"; ValueData: "{#OpenClsid}"
Root: HKCU; Subkey: "Software\Classes\Applications\{#AppExe}\SupportedTypes"; ValueType: string; ValueName: ".xlsx"; ValueData: ""
Root: HKCU; Subkey: "{#CapabilitiesKey}\FileAssociations"; ValueType: string; ValueName: ".xlsx"; ValueData: "{#SheetProgId}"
Root: HKCU; Subkey: "Software\Classes\.xlsx"; Flags: uninsdeletekeyifempty
Root: HKCU; Subkey: "Software\Classes\.xlsx\OpenWithProgids"; ValueType: string; ValueName: "{#SheetProgId}"; ValueData: ""; Flags: uninsdeletevalue uninsdeletekeyifempty
Root: HKCU; Subkey: "Software\Classes\Applications\{#AppExe}\SupportedTypes"; ValueType: string; ValueName: ".xls"; ValueData: ""
Root: HKCU; Subkey: "{#CapabilitiesKey}\FileAssociations"; ValueType: string; ValueName: ".xls"; ValueData: "{#SheetProgId}"
Root: HKCU; Subkey: "Software\Classes\.xls"; Flags: uninsdeletekeyifempty
Root: HKCU; Subkey: "Software\Classes\.xls\OpenWithProgids"; ValueType: string; ValueName: "{#SheetProgId}"; ValueData: ""; Flags: uninsdeletevalue uninsdeletekeyifempty
Root: HKCU; Subkey: "Software\Classes\Applications\{#AppExe}\SupportedTypes"; ValueType: string; ValueName: ".xlsm"; ValueData: ""
Root: HKCU; Subkey: "{#CapabilitiesKey}\FileAssociations"; ValueType: string; ValueName: ".xlsm"; ValueData: "{#SheetProgId}"
Root: HKCU; Subkey: "Software\Classes\.xlsm"; Flags: uninsdeletekeyifempty
Root: HKCU; Subkey: "Software\Classes\.xlsm\OpenWithProgids"; ValueType: string; ValueName: "{#SheetProgId}"; ValueData: ""; Flags: uninsdeletevalue uninsdeletekeyifempty
Root: HKCU; Subkey: "Software\Classes\Applications\{#AppExe}\SupportedTypes"; ValueType: string; ValueName: ".ods"; ValueData: ""
Root: HKCU; Subkey: "{#CapabilitiesKey}\FileAssociations"; ValueType: string; ValueName: ".ods"; ValueData: "{#SheetProgId}"
Root: HKCU; Subkey: "Software\Classes\.ods"; Flags: uninsdeletekeyifempty
Root: HKCU; Subkey: "Software\Classes\.ods\OpenWithProgids"; ValueType: string; ValueName: "{#SheetProgId}"; ValueData: ""; Flags: uninsdeletevalue uninsdeletekeyifempty
Root: HKCU; Subkey: "Software\Classes\{#SlidesProgId}"; ValueType: string; ValueName: ""; ValueData: "Präsentation"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\{#SlidesProgId}"; ValueType: string; ValueName: "FriendlyTypeName"; ValueData: "Präsentation"
Root: HKCU; Subkey: "Software\Classes\{#SlidesProgId}"; ValueType: string; ValueName: "AppUserModelID"; ValueData: "{#AppUserModelID}"
Root: HKCU; Subkey: "Software\Classes\{#SlidesProgId}\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"",{#SlidesIcon}"
Root: HKCU; Subkey: "Software\Classes\{#SlidesProgId}\shell\open"; ValueType: string; ValueName: "FriendlyAppName"; ValueData: "{#AppName}"
Root: HKCU; Subkey: "Software\Classes\{#SlidesProgId}\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" ""%1"""
Root: HKCU; Subkey: "Software\Classes\{#SlidesProgId}\shell\open\command"; ValueType: string; ValueName: "DelegateExecute"; ValueData: "{#OpenClsid}"
Root: HKCU; Subkey: "Software\Classes\Applications\{#AppExe}\SupportedTypes"; ValueType: string; ValueName: ".pptx"; ValueData: ""
Root: HKCU; Subkey: "{#CapabilitiesKey}\FileAssociations"; ValueType: string; ValueName: ".pptx"; ValueData: "{#SlidesProgId}"
Root: HKCU; Subkey: "Software\Classes\.pptx"; Flags: uninsdeletekeyifempty
Root: HKCU; Subkey: "Software\Classes\.pptx\OpenWithProgids"; ValueType: string; ValueName: "{#SlidesProgId}"; ValueData: ""; Flags: uninsdeletevalue uninsdeletekeyifempty
Root: HKCU; Subkey: "Software\Classes\Applications\{#AppExe}\SupportedTypes"; ValueType: string; ValueName: ".ppt"; ValueData: ""
Root: HKCU; Subkey: "{#CapabilitiesKey}\FileAssociations"; ValueType: string; ValueName: ".ppt"; ValueData: "{#SlidesProgId}"
Root: HKCU; Subkey: "Software\Classes\.ppt"; Flags: uninsdeletekeyifempty
Root: HKCU; Subkey: "Software\Classes\.ppt\OpenWithProgids"; ValueType: string; ValueName: "{#SlidesProgId}"; ValueData: ""; Flags: uninsdeletevalue uninsdeletekeyifempty
Root: HKCU; Subkey: "Software\Classes\Applications\{#AppExe}\SupportedTypes"; ValueType: string; ValueName: ".pptm"; ValueData: ""
Root: HKCU; Subkey: "{#CapabilitiesKey}\FileAssociations"; ValueType: string; ValueName: ".pptm"; ValueData: "{#SlidesProgId}"
Root: HKCU; Subkey: "Software\Classes\.pptm"; Flags: uninsdeletekeyifempty
Root: HKCU; Subkey: "Software\Classes\.pptm\OpenWithProgids"; ValueType: string; ValueName: "{#SlidesProgId}"; ValueData: ""; Flags: uninsdeletevalue uninsdeletekeyifempty
Root: HKCU; Subkey: "Software\Classes\Applications\{#AppExe}\SupportedTypes"; ValueType: string; ValueName: ".odp"; ValueData: ""
Root: HKCU; Subkey: "{#CapabilitiesKey}\FileAssociations"; ValueType: string; ValueName: ".odp"; ValueData: "{#SlidesProgId}"
Root: HKCU; Subkey: "Software\Classes\.odp"; Flags: uninsdeletekeyifempty
Root: HKCU; Subkey: "Software\Classes\.odp\OpenWithProgids"; ValueType: string; ValueName: "{#SlidesProgId}"; ValueData: ""; Flags: uninsdeletevalue uninsdeletekeyifempty
Root: HKCU; Subkey: "Software\Classes\{#CsvProgId}"; ValueType: string; ValueName: ""; ValueData: "CSV-Datei"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\{#CsvProgId}"; ValueType: string; ValueName: "FriendlyTypeName"; ValueData: "CSV-Datei"
Root: HKCU; Subkey: "Software\Classes\{#CsvProgId}"; ValueType: string; ValueName: "AppUserModelID"; ValueData: "{#AppUserModelID}"
Root: HKCU; Subkey: "Software\Classes\{#CsvProgId}\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"",{#CsvIcon}"
Root: HKCU; Subkey: "Software\Classes\{#CsvProgId}\shell\open"; ValueType: string; ValueName: "FriendlyAppName"; ValueData: "{#AppName}"
Root: HKCU; Subkey: "Software\Classes\{#CsvProgId}\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" ""%1"""
Root: HKCU; Subkey: "Software\Classes\{#CsvProgId}\shell\open\command"; ValueType: string; ValueName: "DelegateExecute"; ValueData: "{#OpenClsid}"
Root: HKCU; Subkey: "Software\Classes\Applications\{#AppExe}\SupportedTypes"; ValueType: string; ValueName: ".csv"; ValueData: ""
Root: HKCU; Subkey: "{#CapabilitiesKey}\FileAssociations"; ValueType: string; ValueName: ".csv"; ValueData: "{#CsvProgId}"
Root: HKCU; Subkey: "Software\Classes\.csv"; Flags: uninsdeletekeyifempty
Root: HKCU; Subkey: "Software\Classes\.csv\OpenWithProgids"; ValueType: string; ValueName: "{#CsvProgId}"; ValueData: ""; Flags: uninsdeletevalue uninsdeletekeyifempty

[Run]
Filename: "{app}\{#AppExe}"; WorkingDir: "{app}"; Description: "{cm:LaunchApp}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Zur Laufzeit entstandene Dateien im Programmordner
Type: filesandordirs; Name: "{app}\runtime"
Type: filesandordirs; Name: "{app}\app"
Type: filesandordirs; Name: "{app}\assets"
Type: filesandordirs; Name: "{app}\ocr"
Type: filesandordirs; Name: "{app}\ai"
Type: filesandordirs; Name: "{app}\office"
; Profil von LibreOffice und umgewandelte Ansichten von Office-Dateien (seit 5.0) – nur Zwischenablage, keine Benutzerdaten
Type: filesandordirs; Name: "{localappdata}\PDF-Tool-Office"
Type: files; Name: "{app}\fehler.log"
Type: files; Name: "{app}\start.log"
Type: dirifempty; Name: "{app}"
; Heruntergeladene Updates (seit 2.7.2) – nur die eigenen Dateien, keine Benutzerdaten
Type: files; Name: "{localappdata}\PDF-Tool-Updates\PDF-Tool-Setup-*"
Type: files; Name: "{localappdata}\PDF-Tool-Updates\releases.json"
Type: files; Name: "{localappdata}\PDF-Tool-Updates\update-start.log"
Type: dirifempty; Name: "{localappdata}\PDF-Tool-Updates"
; Sprachmodelle des KI-Assistenten (seit 3.2, nur auf Wunsch geladen) – nur die eigenen Dateien
Type: files; Name: "{localappdata}\PDF-Tool-KI\modelle\Qwen3.5-*.gguf"
Type: files; Name: "{localappdata}\PDF-Tool-KI\modelle\Qwen3.5-*.gguf.part"
Type: files; Name: "{localappdata}\PDF-Tool-KI\modelle\Qwen3.5-*.gguf.sha256"
Type: dirifempty; Name: "{localappdata}\PDF-Tool-KI\modelle"
Type: dirifempty; Name: "{localappdata}\PDF-Tool-KI"

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

function PdfToolUpdate(): Boolean;
begin
  Result := (PreviousVersion <> '') and (PreviousName = '{#PdfToolName}');
end;

function RenamedUpdate(): Boolean;
begin
  Result := (PreviousVersion <> '') and (PreviousName <> '{#AppName}') and not PdfToolUpdate();
end;

procedure InitializeWizard();
begin
  if PdfToolUpdate() then
    WizardForm.WelcomeLabel2.Caption := FmtMessage(CustomMessage('NovadeskWelcome'), [PreviousVersion])
  else if RenamedUpdate() then
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
    { Einträge unter dem alten Namen »PDF Tool« (bis 4.0): Standard-Apps und »Start mit Windows« (den setzt die
      App beim nächsten Start unter »Novadesk« neu, wenn die Einstellung an ist) }
    RegDeleteValue(HKCU, 'Software\RegisteredApplications', '{#PdfToolName}');
    RegDeleteValue(HKCU, '{#RunKey}', '{#PdfToolName}');
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
  if CurUninstallStep = usUninstall then
    { »Im Hintergrund bereithalten«: den Eintrag unter »Start mit Windows« setzt die App selbst }
  begin
    RegDeleteValue(HKCU, '{#RunKey}', '{#AppName}');
    RegDeleteValue(HKCU, '{#RunKey}', '{#PdfToolName}');
    RegDeleteValue(HKCU, 'Software\RegisteredApplications', '{#PdfToolName}');
  end;
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
