# Build CropSetup.exe (real Windows installer)
# Copies sources to a local Windows folder first (venv cannot live on \\wsl$ paths).
#
#   powershell -ExecutionPolicy Bypass -File .\scripts\windows\build-installer.ps1

param(
    [string]$SourceDir = ""
)

$ErrorActionPreference = "Stop"

function Step($m) { Write-Host ""; Write-Host "==> $m" -ForegroundColor Cyan }
function Ok($m) { Write-Host "    $m" -ForegroundColor Green }
function Warn($m) { Write-Host "    $m" -ForegroundColor Yellow }

function Refresh-Path {
    $machine = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $user = [Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path = "$machine;$user"
}

if (-not $SourceDir) {
    $here = Split-Path -Parent $MyInvocation.MyCommand.Path
    $SourceDir = (Resolve-Path (Join-Path $here "..\..")).Path
}

# Always build on a real NTFS path
$WorkRoot = Join-Path $env:LOCALAPPDATA "Crop-build"
$WorkSrc = Join-Path $WorkRoot "src"
$DistOut = Join-Path $WorkRoot "dist"
$OutCopy = Join-Path $SourceDir "dist"

Step "Preparing local Windows build folder"
Ok "Source: $SourceDir"
Ok "Work:   $WorkSrc"
if (Test-Path $WorkSrc) {
    Remove-Item $WorkSrc -Recurse -Force -ErrorAction SilentlyContinue
}
New-Item -ItemType Directory -Force -Path $WorkSrc, $DistOut | Out-Null

# Copy needed files only
$excludeDirs = @(".venv", ".venv-win-build", ".run", ".tools", "build", "dist", ".git", "__pycache__")
Get-ChildItem $SourceDir -Force | ForEach-Object {
    if ($excludeDirs -contains $_.Name) { return }
    $dest = Join-Path $WorkSrc $_.Name
    if ($_.PSIsContainer) {
        robocopy $_.FullName $dest /E /XD .venv __pycache__ .git build dist .tools /NFL /NDL /NJH /NJS /nc /ns /np | Out-Null
        if ($LASTEXITCODE -ge 8) { throw "robocopy failed for $($_.Name)" }
    } else {
        Copy-Item $_.FullName $dest -Force
    }
}
Ok "Sources copied"

Set-Location $WorkSrc
$Specs = Join-Path $WorkSrc "scripts\windows"
$InnoScript = Join-Path $Specs "CropSetup.iss"
$Build = Join-Path $WorkRoot "pyi-work"
$Tools = Join-Path $WorkRoot "tools"
$InnoDir = Join-Path $Tools "InnoSetup"
New-Item -ItemType Directory -Force -Path $Build, $Tools | Out-Null

# Patch Inno OutputDir to absolute local dist
$iss = Get-Content $InnoScript -Raw
$iss = $iss -replace 'OutputDir=.*', ("OutputDir=" + $DistOut)
Set-Content -Path $InnoScript -Value $iss -Encoding ASCII

# --- Python ---
Step "Finding Windows Python"
function Find-Python {
    $candidates = @(
        "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe",
        "$env:ProgramFiles\Python312\python.exe"
    )
    foreach ($c in $candidates) { if (Test-Path $c) { return $c } }
    foreach ($cmd in @("python", "python3")) {
        try {
            $p = (Get-Command $cmd -ErrorAction Stop).Source
            if ($p -match "WindowsApps") { continue }
            & $p -c "import sys; assert sys.version_info >= (3, 10)" 2>$null
            if ($LASTEXITCODE -eq 0) { return $p }
        } catch {}
    }
    return $null
}

$Python = Find-Python
if (-not $Python) {
    Warn "Python missing - installing with winget..."
    winget install -e --id Python.Python.3.12 --scope user --accept-package-agreements --accept-source-agreements
    Refresh-Path
    $Python = Find-Python
    if (-not $Python) {
        throw "Python not found after winget install. Open a new PowerShell and re-run."
    }
}
Ok "Python: $Python"

# --- Build venv ---
Step "Preparing build venv"
$PackVenv = Join-Path $WorkRoot "venv"
$PackPy = Join-Path $PackVenv "Scripts\python.exe"
if (-not (Test-Path $PackPy)) {
    & $Python -m venv $PackVenv
}
& $PackPy -m pip install --upgrade pip
& $PackPy -m pip install -r (Join-Path $WorkSrc "requirements.txt")
& $PackPy -m pip install pyinstaller
Ok "PyInstaller ready"

# --- Freeze ---
Step "Building Crop.exe"
Remove-Item (Join-Path $DistOut "Crop.exe") -Force -ErrorAction SilentlyContinue
& $PackPy -m PyInstaller --noconfirm --clean `
    --distpath $DistOut --workpath (Join-Path $Build "Crop") `
    (Join-Path $Specs "Crop.spec")
if (-not (Test-Path (Join-Path $DistOut "Crop.exe"))) { throw "Crop.exe was not produced" }
Ok "Crop.exe"

Step "Building CropControl.exe"
Remove-Item (Join-Path $DistOut "CropControl.exe") -Force -ErrorAction SilentlyContinue
& $PackPy -m PyInstaller --noconfirm --clean `
    --distpath $DistOut --workpath (Join-Path $Build "CropControl") `
    (Join-Path $Specs "CropControl.spec")
if (-not (Test-Path (Join-Path $DistOut "CropControl.exe"))) { throw "CropControl.exe was not produced" }
Ok "CropControl.exe"

Step "Building Windows-compatible icon (BMP ICO for Setup)"
$IconPng = Join-Path $Specs "crop-icon.png"
if (-not (Test-Path $IconPng)) { $IconPng = Join-Path $WorkSrc "app\crop-icon.png" }
$IconIco = Join-Path $Specs "crop-icon.ico"
& $PackPy -c @"
from pathlib import Path
from PIL import Image
src = Image.open(r'$IconPng').convert('RGBA')
sizes = [(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)]
out = Path(r'$IconIco')
src.save(out, format='ICO', sizes=sizes, bitmap_format='bmp')
print('wrote', out, out.stat().st_size)
"@
Copy-Item $IconIco (Join-Path $DistOut "crop-icon.ico") -Force
Copy-Item $IconIco (Join-Path $WorkSrc "app\crop-icon.ico") -Force -ErrorAction SilentlyContinue
Ok "crop-icon.ico (BMP)"

# Point Inno [Files] at DistOut - specs already write there; update Source paths in iss
$issBody = @"
; Auto-patched by build-installer.ps1
#define MyAppName "WDG Crop System"
#define MyAppVersion "2.0.1"
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
DisableDirPage=no
UsePreviousAppDir=yes
PrivilegesRequired=lowest
CloseApplications=yes
CloseApplicationsFilter=Crop.exe,CropControl.exe
RestartApplications=no
OutputDir=$DistOut
OutputBaseFilename=CropSetup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
SetupIconFile=$DistOut\crop-icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
SetupLogging=yes
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Messages]
WelcomeLabel2=This will install [name/ver] on your computer.%n%nWDG Crop System by WebDGallery.%nDeveloped by Md Solaiman.%n%nThe app runs only when you open it.

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Desktop shortcut:"; Flags: unchecked

[Files]
Source: "$DistOut\Crop.exe"; DestDir: "{app}"; Flags: ignoreversion restartreplace
Source: "$DistOut\CropControl.exe"; DestDir: "{app}"; Flags: ignoreversion restartreplace
Source: "$DistOut\crop-icon.ico"; DestDir: "{app}"; Flags: ignoreversion

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

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ResultCode: Integer;
  I: Integer;
begin
  Result := '';
  NeedsRestart := False;
  { Do NOT use taskkill /T — can kill Setup if it is a child of Crop.exe }
  for I := 1 to 6 do
  begin
    Exec('taskkill.exe', '/F /IM Crop.exe', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
    Exec('taskkill.exe', '/F /IM CropControl.exe', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
    Sleep(500);
  end;
  Sleep(1000);
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
"@
$GeneratedIss = Join-Path $WorkRoot "CropSetup.generated.iss"
Set-Content -Path $GeneratedIss -Value $issBody -Encoding ASCII

# --- Inno ---
Step "Locating Inno Setup compiler (ISCC)"
function Find-ISCC {
    $paths = @(
        "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
        (Join-Path $InnoDir "ISCC.exe")
    )
    foreach ($p in $paths) { if (Test-Path $p) { return $p } }
    $found = Get-ChildItem -Path "$env:LOCALAPPDATA\Programs","${env:ProgramFiles(x86)}","$env:ProgramFiles" -Filter ISCC.exe -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty FullName
    if ($found) { return $found }
    return $null
}

$ISCC = Find-ISCC
if (-not $ISCC) {
    Warn "Inno Setup not found - installing..."
    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if ($winget) {
        winget install -e --id JRSoftware.InnoSetup --accept-package-agreements --accept-source-agreements
        Refresh-Path
        Start-Sleep -Seconds 2
        $ISCC = Find-ISCC
    }
    if (-not $ISCC) {
        $setup = Join-Path $Tools "innosetup-install.exe"
        Invoke-WebRequest -Uri "https://jrsoftware.org/download.php/is.exe" -OutFile $setup
        if ((Get-Item $setup).Length -lt 1000000) {
            throw "Inno Setup download looks invalid. Install manually from https://jrsoftware.org/isinfo.php"
        }
        Start-Process -FilePath $setup -ArgumentList "/VERYSILENT","/SUPPRESSMSGBOXES","/NORESTART","/DIR=`"$InnoDir`"" -Wait
        $ISCC = Find-ISCC
    }
    if (-not $ISCC) {
        throw "Could not install Inno Setup. Install from https://jrsoftware.org/isinfo.php then re-run."
    }
}
Ok "ISCC: $ISCC"

Step "Compiling CropSetup.exe"
& $ISCC $GeneratedIss
$Setup = Join-Path $DistOut "CropSetup.exe"
if (-not (Test-Path $Setup)) { throw "CropSetup.exe was not produced" }

# Copy installer back to project dist (best effort on \\wsl$ )
Step "Copying installer to project dist"
New-Item -ItemType Directory -Force -Path $OutCopy | Out-Null
Copy-Item $Setup (Join-Path $OutCopy "CropSetup.exe") -Force
Copy-Item (Join-Path $DistOut "Crop.exe") (Join-Path $OutCopy "Crop.exe") -Force -ErrorAction SilentlyContinue
Copy-Item (Join-Path $DistOut "CropControl.exe") (Join-Path $OutCopy "CropControl.exe") -Force -ErrorAction SilentlyContinue
Copy-Item (Join-Path $Specs "crop-icon.ico") (Join-Path $DistOut "crop-icon.ico") -Force -ErrorAction SilentlyContinue

# Also drop a copy on the Desktop for easy access
$Desktop = [Environment]::GetFolderPath("Desktop")
Copy-Item $Setup (Join-Path $Desktop "CropSetup.exe") -Force
Ok "Desktop\CropSetup.exe"

$hash = (Get-FileHash $Setup -Algorithm SHA256).Hash
$sizeMB = [math]::Round((Get-Item $Setup).Length / 1MB, 1)

Write-Host ""
Write-Host "SUCCESS - installer built:" -ForegroundColor Green
Write-Host "  $Setup"
Write-Host "  Also copied to Desktop: CropSetup.exe"
Write-Host "  Project dist: $OutCopy\CropSetup.exe"
Write-Host "  Size: $sizeMB MB"
Write-Host "  SHA256: $hash"
Write-Host ""
Write-Host "Double-click CropSetup.exe (Next -> Install -> Finish)." -ForegroundColor Green
