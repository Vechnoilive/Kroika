#ifndef AppVersion
  #error AppVersion required
#endif
#ifndef BundleDir
  #error BundleDir required
#endif
#ifndef OutputDir
  #error OutputDir required
#endif
#ifndef RuntimeInstaller
  #error RuntimeInstaller required
#endif
#ifndef AppIcon
  #error AppIcon required
#endif

[Setup]
AppId={{690F227D-12F9-4B39-8D86-F37DA3023B62}
AppName=Кройка
AppVersion={#AppVersion}
AppPublisher=Kroika
AppPublisherURL=https://github.com/Vechnoilive/Kroika
AppUpdatesURL=https://github.com/Vechnoilive/Kroika/releases
DefaultDirName={localappdata}\Programs\Kroika
DefaultGroupName=Кройка
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763
UsePreviousAppDir=yes
DisableProgramGroupPage=yes
OutputDir={#OutputDir}
OutputBaseFilename=Kroika-{#AppVersion}-windows-x64-setup
SetupIconFile={#AppIcon}
UninstallDisplayIcon={app}\Kroika.exe
Compression=lzma2/fast
SolidCompression=yes
WizardStyle=modern
CloseApplications=no
RestartApplications=no
AppMutex=Kroika.Desktop.Window
Uninstallable=yes

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"

[Tasks]
Name: "desktopicon"; Description: "Создать ярлык на рабочем столе"; Flags: unchecked

[InstallDelete]
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "{#BundleDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#RuntimeInstaller}"; DestDir: "{tmp}"; DestName: "MicrosoftEdgeWebView2RuntimeInstallerX64.exe"; Flags: deleteafterinstall; Check: NeedsWebView2

[Icons]
Name: "{userprograms}\Кройка"; Filename: "{app}\Kroika.exe"
Name: "{userdesktop}\Кройка"; Filename: "{app}\Kroika.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\Kroika.exe"; Description: "Открыть Кройку"; Flags: nowait postinstall skipifsilent

[Code]
function NeedsWebView2: Boolean;
var Version: String;
begin
  Result := not ((RegQueryStringValue(HKLM32, 'SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', Version) and (Version <> '') and (Version <> '0.0.0.0')) or
                 (RegQueryStringValue(HKCU, 'SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', Version) and (Version <> '') and (Version <> '0.0.0.0')));
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var ResultCode: Integer;
begin
  Result := '';
  if NeedsWebView2 then begin
    ExtractTemporaryFile('MicrosoftEdgeWebView2RuntimeInstallerX64.exe');
    if not Exec(ExpandConstant('{tmp}\MicrosoftEdgeWebView2RuntimeInstallerX64.exe'), '/silent /install', '', SW_HIDE, ewWaitUntilTerminated, ResultCode) then
      Result := 'Не удалось установить WebView2. Проверьте доступ к папке и повторите установку.'
    else if NeedsWebView2 then
      Result := 'WebView2 не установлен. Установите Microsoft Edge WebView2 Runtime и повторите установку Кройки.';
  end;
end;
