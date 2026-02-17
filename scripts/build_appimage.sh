#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <version>" >&2
  exit 1
fi

VERSION="$1"
ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

BINARY_PATH="$ROOT_DIR/dist/NotesSyncLinux"
if [[ ! -x "$BINARY_PATH" ]]; then
  echo "Missing binary: $BINARY_PATH" >&2
  echo "Run scripts/build_pyinstaller.sh first." >&2
  exit 1
fi

APPDIR="$ROOT_DIR/build/appimage/NotesSyncLinux.AppDir"
TOOL_PATH="$ROOT_DIR/build/appimage/appimagetool-x86_64.AppImage"
OUTPUT="$ROOT_DIR/dist/NotesSyncLinux-${VERSION}-x86_64.AppImage"

rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/bin"

install -m 755 "$BINARY_PATH" "$APPDIR/usr/bin/NotesSyncLinux"
install -m 644 "$ROOT_DIR/assets/linux/notes-sync-linux.svg" "$APPDIR/notes-sync-linux.svg"

sed "s/__VERSION__/${VERSION}/g" \
  "$ROOT_DIR/assets/linux/notes-sync-linux-appimage.desktop" \
  > "$APPDIR/notes-sync-linux.desktop"

cat > "$APPDIR/AppRun" <<'EOF'
#!/usr/bin/env sh
HERE="$(dirname "$(readlink -f "$0")")"
exec "$HERE/usr/bin/NotesSyncLinux" "$@"
EOF
chmod 755 "$APPDIR/AppRun"

ln -sf notes-sync-linux.svg "$APPDIR/.DirIcon"

if [[ ! -x "$TOOL_PATH" ]]; then
  mkdir -p "$(dirname "$TOOL_PATH")"
  curl -fsSL \
    "https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-x86_64.AppImage" \
    -o "$TOOL_PATH"
  chmod 755 "$TOOL_PATH"
fi

ARCH=x86_64 APPIMAGE_EXTRACT_AND_RUN=1 "$TOOL_PATH" "$APPDIR" "$OUTPUT"
echo "Built $OUTPUT"
