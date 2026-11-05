#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
command -v ffmpeg >/dev/null || { echo 'Install FFmpeg first (e.g. brew install ffmpeg or sudo apt install ffmpeg)'; exit 1; }
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python app.py
