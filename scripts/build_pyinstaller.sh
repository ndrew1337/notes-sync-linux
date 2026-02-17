#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

rm -rf build/pyinstaller
rm -f dist/NotesSyncLinux NotesSyncLinux.spec

python3 -m PyInstaller \
  --noconfirm \
  --clean \
  --onefile \
  --windowed \
  --name NotesSyncLinux \
  notes_sync_linux/main.py
