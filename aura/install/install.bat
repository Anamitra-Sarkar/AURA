@echo off
setlocal enabledelayedexpansion
python -m venv .venv
.venv\Scripts\python -m pip install --upgrade pip
.venv\Scripts\pip install -r requirements.txt
echo Install complete. Start AURA with: .venv\Scripts\python -m aura.daemon
