; ── AI-PDF Windows Installer (Inno Setup) ────────────────────────────────
; Build:  iscc packaging/ai-pdf.iss
; Output: packaging/Output/AI-PDF-Setup.exe
;
; Prerequisites:
;   - Run packaging/build_windows.bat first to create dist/AI-PDF/
;   - Inno Setup 6+ installed (https://jrsoftware.org/isdl.php)

#define MyAppName "AI-PDF"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "AI-PDF"
#define MyAppExeName "AI-PDF.exe"
#define MyAppDir "dist\AI-PDF"

[Setup]
AppId={{A1-PDF-2024-0001-0000-000000000001}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=Output
OutputBaseFilename=AI-PDF-Setup
Compression=lzma2/ultra64
SolidCompression=yes
PrivilegesRequired=admin
ArchitecturesInstallIn64BitMode=x64compatible
ArchitecturesAllowed=x64compatible
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName}
WizardStyle=modern
LicenseFile=
InfoBeforeFile=

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop icon"; GroupDescription: "Additional icons:"; Flags: unchecked

[Files]
; Bundle the entire dist/AI-PDF/ folder
Source: "{#MyAppDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}"

[Registry]
; Optional: register .pdf file association
Root: HKCU; Subkey: "Software\Classes\.pdf\OpenWithList\{#MyAppExeName}"; ValueType: none; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\Applications\{#MyAppExeName}\shell\open\command"; ValueType: string; ValueData: """{app}\{#MyAppExeName}"" ""%1"""; Flags: uninsdeletekey
