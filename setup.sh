#!/usr/bin/env bash
set -euo pipefail
umask 077
cd "$(dirname "$0")"
command -v ffmpeg >/dev/null || { echo 'Install FFmpeg first (see README.md).' >&2; exit 1; }
command -v ffprobe >/dev/null || { echo 'FFprobe is required with FFmpeg.' >&2; exit 1; }
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
if [ ! -f .env ]; then cp .env.example .env; fi
printf 'Installed. Run ./start.sh to open the studio.\n'
