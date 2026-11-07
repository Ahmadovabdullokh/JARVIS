#define MyAppName "JARVIS"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "JARVIS"
#define MyAppExeName "JARVIS.exe"

[Setup]
AppId={{B5E7D7A4-6E1D-4F71-9F8B-6E8A0A8D6C11}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\JARVIS
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=..\dist_installer
OutputBaseFilename=JARVIS-Setup
Compression=lzma
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Создать ярлык на рабочем столе"; GroupDescription: "Ярлыки:"
Name: "startup"; Description: "Запускать JARVIS при входе в Windows"; GroupDescription: "Автозапуск:"; Flags: unchecked

[Files]
Source: "..\dist\JARVIS.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\config\config.example.json"; DestDir: "{app}\config"; DestName: "config.json"; Flags: onlyifdoesntexist

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon
Name: "{userstartup}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: startup

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Запустить {#MyAppName}"; Flags: nowait postinstall skipifsilent
