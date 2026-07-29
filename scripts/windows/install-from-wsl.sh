#!/usr/bin/env bash
# Open the Windows installer in PowerShell (from WSL).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
# Convert /home/... to \\wsl$\Distro\home\...
DISTRO="${WSL_DISTRO_NAME:-Ubuntu}"
WIN_PATH=$(wslpath -w "$ROOT")
echo "Opening Windows installer…"
echo "  $WIN_PATH"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "${WIN_PATH}\\scripts\\windows\\install.ps1"
