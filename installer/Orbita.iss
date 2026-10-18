; Compile through build_installer.py. Runtime data never resides in {app}.
#ifndef BundleDir
  #error BundleDir is required
#endif
#ifndef ProductVersion
  #error ProductVersion is required
#endif
#ifndef OutputPath
  #error OutputPath is required
#endif
#ifndef OutputName
  #define OutputName "Orbita-Setup-" + ProductVersion + "-Windows-x64"
#endif
#ifdef TestRoot
  #ifndef TestId
    #error TestId is required for an isolated test build
  #endif
  #define ProductId "Technomedved.Orbita.Test." + TestId
  #define StartupValue "Orbita-Test-" + TestId
  #define GroupName "Orbita Test " + TestId
  #define DefaultPath TestRoot + "\program"
#else
  #define ProductId "Technomedved.Orbita.Desktop"
  #define StartupValue "Orbita"
  #define GroupName "Орбита"
  #define DefaultPath "{localappdata}\Programs\Orbita"
#endif

[Setup]
AppId={#ProductId}
AppName=Орбита
AppVersion={#ProductVersion}
AppPublisher=Technomedved
AppPublisherURL=https://github.com/Technomedved/orbita
AppSupportURL=https://github.com/Technomedved/orbita/issues
AppUpdatesURL=https://github.com/Technomedved/orbita/releases
DefaultDirName={#DefaultPath}
DefaultGroupName={#GroupName}
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.22000
DisableProgramGroupPage=yes
DisableDirPage=auto
UsePreviousAppDir=yes
WizardStyle=modern dark
UninstallDisplayIcon={app}\Orbita.exe
UninstallDisplayName=Орбита
OutputDir={#OutputPath}
OutputBaseFilename={#OutputName}
Compression=lzma2/fast
SolidCompression=yes
CloseApplications=no
RestartApplications=no
AppMutex={code:GetAppMutexes}
SetupMutex=Local\Orbita.Setup
LicenseFile={#BundleDir}\LICENSE
InfoBeforeFile={#SourcePath}INSTALLER.txt
UninstallLogMode=append

[Languages]
Name: russian; MessagesFile: compiler:Languages\Russian.isl
Name: english; MessagesFile: compiler:Default.isl

[Tasks]
Name: desktopicon; Description: "{cm:CreateDesktopIcon}"; Flags: unchecked

[Files]
Source: "{#BundleDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[INI]
Filename: "{app}\orbita-installation.ini"; Section: "Installation"; Key: "ProductId"; String: "{#ProductId}"; Flags: uninsdeleteentry uninsdeletesectionifempty

[Icons]
Name: "{group}\Орбита"; Filename: "{app}\Orbita.exe"; WorkingDir: "{app}"
Name: "{group}\Удалить Орбиту"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Орбита"; Filename: "{app}\Orbita.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\Orbita.exe"; Description: "Запустить Орбиту"; Flags: nowait postinstall skipifsilent

[InstallDelete]
; Only product-owned dependency/content trees, after checking for junctions.
Type: filesandordirs; Name: "{app}\_internal"; Check: ExistingOwnedInstall
Type: filesandordirs; Name: "{app}\docs"; Check: ExistingOwnedInstall
Type: filesandordirs; Name: "{app}\licenses"; Check: ExistingOwnedInstall
Type: filesandordirs; Name: "{app}\training"; Check: ExistingOwnedInstall

[UninstallDelete]
Type: files; Name: "{app}\orbita-installation.ini"

[Messages]
russian.SetupAppRunningError=Орбита сейчас работает.%n%nВ меню значка Орбиты в системном трее выберите «Выход». Крестик окна только скрывает панель.%n%nЗатем нажмите «OK», чтобы продолжить, или «Отмена».
russian.UninstallAppRunningError=Орбита сейчас работает.%n%nВ меню значка Орбиты в системном трее выберите «Выход», затем повторите удаление. Крестик окна только скрывает панель.
english.SetupAppRunningError=Orbita is running.%n%nChoose Exit from its system tray menu. Closing the window only hides it.%n%nThen click OK to continue, or Cancel.
english.UninstallAppRunningError=Orbita is running.%n%nChoose Exit from its system tray menu, then retry uninstalling. Closing the window only hides it.

[Code]
var
  PurgeProfile: Boolean;
  SelectedProfile: String;

function NativeFileAttributes(const Name: String): Cardinal;
  external 'GetFileAttributesW@kernel32.dll stdcall';

function IsLink(const Name: String): Boolean;
var Attr: Cardinal;
begin
  Attr := NativeFileAttributes(Name);
  Result := (Attr <> $FFFFFFFF) and ((Attr and $400) <> 0);
end;

function DefaultProfile: String;
var Modern, Legacy: String;
begin
#ifdef TestRoot
  Result := '{#TestRoot}\profile';
#else
  Modern := ExpandConstant('{localappdata}\Orbita');
  Legacy := ExpandConstant('{localappdata}\UrayAssistant');
  if (not FileExists(Modern + '\inbox.sqlite')) and FileExists(Legacy + '\inbox.sqlite') then
    Result := Legacy
  else
    Result := Modern;
#endif
end;

function ProfileMutex(const Folder: String): String;
var Key: AnsiString;
begin
  Key := UTF8Encode(Lowercase(ExpandFileName(Folder)));
  Result := 'Local\OrbitaDesktop-' + Copy(Lowercase(GetSHA256OfString(Key)), 1, 24);
end;

function GetAppMutexes(Param: String): String;
begin
  Result := 'Local\Orbita.Desktop.InstallGuard,' + ProfileMutex(DefaultProfile);
#ifndef TestRoot
  Result := Result + ',' + ProfileMutex(ExpandConstant('{localappdata}\Orbita')) + ',' + ProfileMutex(ExpandConstant('{localappdata}\UrayAssistant'));
#endif
end;

function ExistingOwnedInstall: Boolean;
begin
  Result := GetIniString('Installation', 'ProductId', '', ExpandConstant('{app}\orbita-installation.ini')) = '{#ProductId}';
end;

function IsNonEmptyDirectory(const Folder: String): Boolean;
var Entry: TFindRec;
begin
  Result := False;
  if FindFirst(AddBackslash(Folder) + '*', Entry) then begin
    try
      repeat
        if (Entry.Name <> '.') and (Entry.Name <> '..') then begin Result := True; Break; end;
      until not FindNext(Entry);
    finally FindClose(Entry); end;
  end;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var App, Item: String; I: Integer;
begin
  Result := '';
  if CheckForMutexes(GetAppMutexes('')) then begin
    Result := 'Завершите Орбиту через меню трея → Выход и повторите установку.';
    Exit;
  end;
  App := ExpandConstant('{app}');
  if IsLink(App) then begin Result := 'Папка программы не должна быть ссылкой или junction.'; Exit; end;
  if DirExists(App) and IsNonEmptyDirectory(App) and not ExistingOwnedInstall then begin
    Result := 'Выберите отдельную пустую папку для Орбиты. Существующая папка не принадлежит установщику; её файлы не будут заменены.';
    Exit;
  end;
  for I := 0 to 3 do begin
    case I of
      0: Item := '_internal';
      1: Item := 'docs';
      2: Item := 'licenses';
      3: Item := 'training';
    end;
    if IsLink(AddBackslash(App) + Item) then begin Result := 'Удалите ссылку из папки программы перед обновлением: ' + Item; Exit; end;
  end;
end;

function InitializeUninstall: Boolean;
var Answer: Integer;
begin
  PurgeProfile := False;
  SelectedProfile := DefaultProfile;
  Result := True;
#ifdef TestRoot
  if ExpandConstant('{param:PURGETESTDATA|no}') = 'yes' then PurgeProfile := True;
#endif
  if not UninstallSilent and DirExists(SelectedProfile) then begin
    Answer := SuppressibleMsgBox('Удалить также личные данные Орбиты?' + #13#10 + #13#10 +
      'Напоминания, проекты, ответы, история, настройки и резервные копии в:' + #13#10 + SelectedProfile + #13#10 + #13#10 +
      '«Нет» сохраняет данные для следующей установки. Отдельные профили AUTOMATION_HOME не затрагиваются.',
      mbConfirmation, MB_YESNOCANCEL or MB_DEFBUTTON2, IDNO);
    Result := Answer <> IDCANCEL;
    PurgeProfile := Answer = IDYES;
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var Value, OwnCommand: String;
begin
  if CurUninstallStep = usPostUninstall then begin
    OwnCommand := '"' + ExpandConstant('{app}\Orbita.exe') + '" --background';
    { Pascal registry functions use an explicit view; match the x64 Python app. }
    if RegQueryStringValue(HKCU64, 'Software\Microsoft\Windows\CurrentVersion\Run', '{#StartupValue}', Value) then
      if CompareText(Trim(Value), OwnCommand) = 0 then
        RegDeleteValue(HKCU64, 'Software\Microsoft\Windows\CurrentVersion\Run', '{#StartupValue}');
    if PurgeProfile then begin
      { The target is recomputed and must exactly equal the single selected default profile.
        Inno DelTree removes reparse points themselves and never traverses their targets. }
      if (SelectedProfile <> '') and (CompareText(ExpandFileName(SelectedProfile), ExpandFileName(DefaultProfile)) = 0) then begin
        if not DelTree(SelectedProfile, True, True, True) then begin
          Log('Some profile data could not be removed: ' + SelectedProfile);
          if not UninstallSilent then MsgBox('Часть данных не удалось удалить. Проверьте папку: ' + SelectedProfile, mbInformation, MB_OK);
        end;
      end;
    end;
  end;
end;
