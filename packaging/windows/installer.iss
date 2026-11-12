; Inno Setup script for the LOR Sequencer Windows installer.
; Built by .github/workflows/desktop.yml after PyInstaller has made "dist\LOR Sequencer".
; Local build (from the repository root):
;   iscc /DAppVersion=0.1.0 packaging\windows\installer.iss
; Running a newer (or the same) installer over an existing install replaces it in place:
; same AppId and folder, the running app is closed first, and old program files are
; cleared so nothing stale is left behind. Settings and show files are not touched.
; Installs for the current user only (no administrator prompt), adds a Start menu
; entry and an optional desktop shortcut, and uninstalls cleanly from Settings > Apps.

#ifndef AppVersion
  #define AppVersion "0.1.0"
#endif
#define AppName "LOR Sequencer"
#define AppExe "LOR Sequencer.exe"

[Setup]
AppId={{5bb5eee5-ba51-5866-a395-7b61cac7eea3}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=Light-O-Rama Sequence Builder project
AppPublisherURL=https://github.com/MikeAllen1/light-o-rama-sequence-builder
AppSupportURL=https://github.com/MikeAllen1/light-o-rama-sequence-builder/issues
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\..\dist
OutputBaseFilename=LOR-Sequencer-Setup-{#AppVersion}
SetupIconFile=lor-sequencer.ico
UninstallDisplayIcon={app}\{#AppExe}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
LicenseFile=..\..\LICENSE
UsePreviousAppDir=yes
UsePreviousTasks=yes
CloseApplications=force
CloseApplicationsFilter=*.exe,*.dll,*.pyd
RestartApplications=no

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"

[InstallDelete]
; The previous version's program files (PyInstaller's _internal folder); user data lives elsewhere.
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "..\..\dist\LOR Sequencer\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "Start {#AppName} now"; Flags: nowait postinstall skipifsilent
