; Crop — Inno Setup installer
; Output: dist\CropSetup.exe

#define MyAppName "WDG Crop System"
#define MyAppVersion "1.0.2"
#define MyAppPublisher "WebDGallery"
#define MyAppURL "https://github.com/nirjondipo/crop"
#define MyAppExeName "Crop.exe"
#define MyControlExeName "CropControl.exe"

[Setup]
AppId={{8F3C2A1B-9D4E-4F6A-B7C8-1E2D3A4B5C6D}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
DefaultDirName={localappdata}\Crop
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
; Ask user to confirm / change install folder
DisableDirPage=no
UsePreviousAppDir=yes
PrivilegesRequired=lowest
OutputDir=..\..\dist
OutputBaseFilename=CropSetup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
SetupIconFile=crop-icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
SetupLogging=yes
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Messages]
WelcomeLabel2=This will install [name/ver] on your computer.%n%nWDG Crop System by WebDGallery.%nDeveloped by Md Solaiman.%n%nThe app runs only when you open it. Nothing starts at Windows login.
WizardSelectDirLabel3=Setup will install WDG Crop System into the following folder. You can keep the default or choose another location.
WizardSelectTasksLabel2=Select the optional tasks you want Setup to perform, then click Next.

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Desktop shortcut:"; Flags: unchecked

[Files]
Source: "..\..\dist\Crop.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\..\dist\CropControl.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "crop-icon.ico"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\..\README.md"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\crop-icon.ico"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\crop-icon.ico"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch WDG Crop System"; Flags: nowait postinstall skipifsilent unchecked

[UninstallDelete]
Type: filesandordirs; Name: "{app}\.run"

[UninstallRun]
Filename: "taskkill.exe"; Parameters: "/IM Crop.exe /F"; Flags: runhidden; RunOnceId: "KillCrop"
Filename: "taskkill.exe"; Parameters: "/IM CropControl.exe /F"; Flags: runhidden; RunOnceId: "KillControl"

[Code]
function JsonEscape(const S: String): String;
begin
  Result := S;
  StringChangeEx(Result, '\', '\\', True);
  StringChangeEx(Result, '"', '\"', True);
end;

procedure WriteInstallMarker();
var
  Json: String;
  AppDir: String;
begin
  AppDir := ExpandConstant('{app}');
  Json :=
    '{' + #13#10 +
    '  "installRoot": "' + JsonEscape(AppDir) + '",' + #13#10 +
    '  "exe": "' + JsonEscape(AppDir + '\{#MyAppExeName}') + '",' + #13#10 +
    '  "controlExe": "' + JsonEscape(AppDir + '\{#MyControlExeName}') + '",' + #13#10 +
    '  "version": "{#MyAppVersion}"' + #13#10 +
    '}';
  ForceDirectories(AppDir + '\.run');
  SaveStringToFile(AppDir + '\install.json', Json, False);
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
    WriteInstallMarker();
end;
