[Setup]
AppName=Militech Open Bot Portable
AppVersion=2.92
; Portable: устанавливается куда угодно, не требует прав, не пишет в реестр
DefaultDirName={autopf}\MOB_Portable
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
CreateAppDir=yes
; Не создаём записи в реестре и меню пуск по умолчанию
CreateUninstallRegKey=no
UpdateUninstallLogAppName=no
OutputDir=.\EXE
OutputBaseFilename=MOB_Portable
SetupIconFile=icon.ico
Compression=lzma2/ultra64
LZMAUseSeparateProcess=yes
LZMANumBlockThreads=4
SolidCompression=yes
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64
; Не добавляем в меню "Установка и удаление программ"
Uninstallable=no
DisableDirPage=no
DisableProgramGroupPage=yes

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; Копируем всю папку portable-сборки
Source: "dist\MOB_Portable\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autodesktop}\Militech Open Bot Portable"; Filename: "{app}\MOB_Portable.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\MOB_Portable.exe"; Description: "{cm:LaunchProgram,Militech Open Bot Portable}"; Flags: nowait postinstall skipifsilent

[Code]
// После установки создаём пустую папку data/ рядом с exe
procedure CurStepChanged(CurStep: TSetupStep);
var
  DataDir: String;
begin
  if CurStep = ssPostInstall then
  begin
    DataDir := ExpandConstant('{app}\data');
    if not DirExists(DataDir) then
      CreateDir(DataDir);
  end;
end;
