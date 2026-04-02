#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="${ROOT_DIR:-$HOME/.local/share/aura}"
VENV_DIR="$ROOT_DIR/.venv"
SERVICE_DIR="$HOME/.config/systemd/user"
SERVICE_FILE="$SERVICE_DIR/aura.service"

mkdir -p "$ROOT_DIR" "$SERVICE_DIR"
python3 -m venv "$VENV_DIR"
"$VENV_DIR/bin/python" -m pip install --upgrade pip
"$VENV_DIR/bin/pip" install -r "$(cd "$(dirname "$0")/.." && pwd)/../requirements.txt"

if ! command -v ollama >/dev/null 2>&1; then
  echo "Ollama is not installed. Install it separately before starting AURA."
else
  echo "Ollama detected."
fi

cp "$(dirname "$0")/aura.service" "$SERVICE_FILE"
systemctl --user daemon-reload
systemctl --user enable aura.service

echo "AURA installed. Start it with: systemctl --user start aura.service"
