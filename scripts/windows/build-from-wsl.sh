#!/usr/bin/env bash
# Kick off the Windows installer build from WSL.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
WIN_PATH=$(wslpath -w "$ROOT")
echo "Building CropSetup.exe via Windows PowerShell…"
echo "  $WIN_PATH"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "${WIN_PATH}\\scripts\\windows\\build-installer.ps1"
echo "If successful: ${WIN_PATH}\\dist\\CropSetup.exe"
