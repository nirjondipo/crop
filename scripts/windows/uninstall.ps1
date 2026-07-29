# Uninstall Crop from %LOCALAPPDATA%\Crop
$ErrorActionPreference = "Continue"
$InstallRoot = Join-Path $env:LOCALAPPDATA "Crop"
$StartupLnk = Join-Path ([Environment]::GetFolderPath("Startup")) "Crop Control.lnk"
$StartMenuDir = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Crop"

Write-Host "Stopping Crop processes…"
try { Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:18765/stop" -TimeoutSec 2 | Out-Null } catch {}
Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -match 'Crop|control_server\.py' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }

Remove-Item $StartupLnk -Force -ErrorAction SilentlyContinue
Remove-Item $StartMenuDir -Recurse -Force -ErrorAction SilentlyContinue
if (Test-Path $InstallRoot) {
    Remove-Item $InstallRoot -Recurse -Force
    Write-Host "Removed $InstallRoot" -ForegroundColor Green
} else {
    Write-Host "Nothing to remove at $InstallRoot"
}
Write-Host "Uninstall complete."
