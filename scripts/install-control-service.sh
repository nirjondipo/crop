#!/usr/bin/env bash
# Install & start Crop control API as a systemd --user service (no root needed).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
UNIT_DIR="${HOME}/.config/systemd/user"
UNIT_FILE="${UNIT_DIR}/crop-control.service"

mkdir -p "${UNIT_DIR}"
cat > "${UNIT_FILE}" <<EOF
[Unit]
Description=Crop desktop app control API
After=default.target

[Service]
Type=simple
WorkingDirectory=${ROOT}
ExecStart=${ROOT}/.venv/bin/python ${ROOT}/scripts/control_server.py
Restart=on-failure
RestartSec=2
Environment=DISPLAY=:0
Environment=XDG_RUNTIME_DIR=%t

[Install]
WantedBy=default.target
EOF

systemctl --user daemon-reload
systemctl --user enable --now crop-control.service
systemctl --user --no-pager status crop-control.service || true
echo "Crop control API: http://127.0.0.1:18765/status"
