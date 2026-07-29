# Crop — native Windows installer
# Run in PowerShell (as your user). Installs to %LOCALAPPDATA%\Crop
# and wires Start Menu + login control API for http://localhost:1000/crop/

param(
    [string]$SourceDir = ""
)

$ErrorActionPreference = "Stop"

function Write-Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }
function Write-Ok($msg) { Write-Host "    $msg" -ForegroundColor Green }
function Write-Warn($msg) { Write-Host "    $msg" -ForegroundColor Yellow }

$InstallRoot = Join-Path $env:LOCALAPPDATA "Crop"
$VenvPython = Join-Path $InstallRoot ".venv\Scripts\python.exe"
$VenvPythonw = Join-Path $InstallRoot ".venv\Scripts\pythonw.exe"
$ControlScript = Join-Path $InstallRoot "scripts\control_server.py"
$MainPy = Join-Path $InstallRoot "main.py"
$StartupDir = [Environment]::GetFolderPath("Startup")
$StartMenuDir = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Crop"

Write-Host "Crop Windows installer" -ForegroundColor White
Write-Host "Install to: $InstallRoot"

# Resolve source (this script's repo root, or \\wsl$\... path)
if (-not $SourceDir) {
    $here = Split-Path -Parent $MyInvocation.MyCommand.Path
    $SourceDir = (Resolve-Path (Join-Path $here "..\..")).Path
}
if (-not (Test-Path (Join-Path $SourceDir "main.py"))) {
    throw "Cannot find main.py in source: $SourceDir"
}
Write-Ok "Source: $SourceDir"

# --- Python ---
Write-Step "Checking Windows Python"
function Find-Python {
    $candidates = @(
        "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe",
        "$env:ProgramFiles\Python312\python.exe",
        "$env:ProgramFiles\Python313\python.exe"
    )
    foreach ($c in $candidates) {
        if (Test-Path $c) { return $c }
    }
    foreach ($cmd in @("python", "python3")) {
        try {
            $p = (Get-Command $cmd -ErrorAction Stop).Source
            # Skip WindowsApps store stub
            if ($p -match "WindowsApps") { continue }
            & $p -c "import sys; assert sys.version_info >= (3, 10)" 2>$null
            if ($LASTEXITCODE -eq 0) { return $p }
        } catch {}
    }
    return $null
}

$Python = Find-Python
if (-not $Python) {
    Write-Warn "Python not found. Trying winget install (user scope)…"
    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if (-not $winget) {
        throw "Install Python 3.12+ from https://www.python.org/downloads/ (check 'Add python.exe to PATH'), then re-run this installer."
    }
    winget install -e --id Python.Python.3.12 --scope user --accept-package-agreements --accept-source-agreements
    Start-Sleep -Seconds 2
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
                [System.Environment]::GetEnvironmentVariable("Path", "User")
    $Python = Find-Python
    if (-not $Python) {
        throw "Python installed but not found on PATH. Close this window, open a new PowerShell, and re-run install.ps1"
    }
}
Write-Ok "Python: $Python"
& $Python -c "import sys; print(sys.version)"

# --- Copy files ---
Write-Step "Copying app files"
New-Item -ItemType Directory -Force -Path $InstallRoot | Out-Null
$exclude = @(".venv", ".run", "__pycache__", ".git", ".pytest_cache")
Get-ChildItem $SourceDir -Force | ForEach-Object {
    if ($exclude -contains $_.Name) { return }
    $dest = Join-Path $InstallRoot $_.Name
    if ($_.PSIsContainer) {
        robocopy $_.FullName $dest /E /XD .venv __pycache__ .git /NFL /NDL /NJH /NJS /nc /ns /np | Out-Null
    } else {
        Copy-Item $_.FullName $dest -Force
    }
}
Write-Ok "Files copied"

# --- venv + deps ---
Write-Step "Creating venv and installing packages"
if (-not (Test-Path $VenvPython)) {
    & $Python -m venv (Join-Path $InstallRoot ".venv")
}
& $VenvPython -m pip install --upgrade pip
& $VenvPython -m pip install -r (Join-Path $InstallRoot "requirements.txt")
Write-Ok "Dependencies ready"

# --- Launchers ---
Write-Step "Creating shortcuts"
New-Item -ItemType Directory -Force -Path $StartMenuDir | Out-Null

$launchBat = Join-Path $InstallRoot "Launch Crop.bat"
@"
@echo off
cd /d "$InstallRoot"
start "" "$VenvPythonw" "$MainPy"
"@ | Set-Content -Encoding ASCII $launchBat

$controlBat = Join-Path $InstallRoot "Start Control.bat"
@"
@echo off
cd /d "$InstallRoot"
"$VenvPythonw" "$ControlScript"
"@ | Set-Content -Encoding ASCII $controlBat

# Start Menu shortcut via WScript
$wsh = New-Object -ComObject WScript.Shell
$sc = $wsh.CreateShortcut((Join-Path $StartMenuDir "Crop.lnk"))
$sc.TargetPath = $launchBat
$sc.WorkingDirectory = $InstallRoot
$sc.WindowStyle = 7
$sc.Description = "Crop - Batch Image Resizer"
$sc.Save()
Write-Ok "Start Menu shortcut created (no login startup - runs only when you open it)"

# Marker for WSL control to prefer Windows app
$marker = @{
    installRoot = $InstallRoot
    pythonw     = $VenvPythonw
    main        = $MainPy
    control     = $ControlScript
    installedAt = (Get-Date).ToString("o")
} | ConvertTo-Json
Set-Content -Path (Join-Path $InstallRoot "install.json") -Value $marker -Encoding UTF8
# Also write where WSL can find it easily
$wslMarkerDir = Join-Path $InstallRoot ".run"
New-Item -ItemType Directory -Force -Path $wslMarkerDir | Out-Null

# --- Stop WSL control if bound, start Windows control ---
Write-Step "Starting Windows control API (port 18765)"
Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -match 'control_server\.py' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }

# Free port if something else holds it briefly
Start-Sleep -Milliseconds 400
Start-Process -FilePath $VenvPythonw -ArgumentList "`"$ControlScript`"" -WorkingDirectory $InstallRoot -WindowStyle Hidden
Start-Sleep -Seconds 1

try {
    $status = Invoke-RestMethod -Uri "http://127.0.0.1:18765/status" -TimeoutSec 3
    Write-Ok ("Control online. running=" + $status.running)
} catch {
    Write-Warn "Control did not respond yet — it should start at next login via Startup folder."
}

Write-Host ""
Write-Host "Done. Crop is installed on Windows." -ForegroundColor Green
Write-Host "  App:      Start Menu → Crop"
Write-Host "  Web:      http://localhost:1000/crop/  (Run / Exit)"
Write-Host "  Folder:   $InstallRoot"
Write-Host ""
Write-Host "This runs as a native Windows app (much faster than WSL)." -ForegroundColor Green
