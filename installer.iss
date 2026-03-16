[Setup]
AppName=Militech Open Bot
AppVersion=2.9
DefaultDirName={localappdata}\MOB
PrivilegesRequired=lowest
DefaultGroupName=Militech Open Bot
OutputDir=.\EXE
OutputBaseFilename=Setup_MOB
SetupIconFile=icon.ico
Compression=lzma2/ultra64
LZMAUseSeparateProcess=yes
LZMANumBlockThreads=4
SolidCompression=yes
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "dist\MOB\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Militech Open Bot"; Filename: "{app}\MOB.exe"
Name: "{autodesktop}\Militech Open Bot"; Filename: "{app}\MOB.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\MOB.exe"; Description: "{cm:LaunchProgram,Militech Open Bot}"; Flags: nowait postinstall skipifsilent