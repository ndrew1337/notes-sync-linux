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

PKG_NAME="notes-sync-linux_${VERSION}_amd64"
STAGE_DIR="$ROOT_DIR/build/deb/$PKG_NAME"
OUT_DEB="$ROOT_DIR/dist/${PKG_NAME}.deb"

rm -rf "$STAGE_DIR"
mkdir -p "$STAGE_DIR/DEBIAN"
mkdir -p "$STAGE_DIR/opt/notes-sync-linux"
mkdir -p "$STAGE_DIR/usr/bin"
mkdir -p "$STAGE_DIR/usr/share/applications"
mkdir -p "$STAGE_DIR/usr/share/icons/hicolor/scalable/apps"

install -m 755 "$BINARY_PATH" "$STAGE_DIR/opt/notes-sync-linux/NotesSyncLinux"
install -m 644 "$ROOT_DIR/assets/linux/notes-sync-linux.desktop" \
  "$STAGE_DIR/usr/share/applications/notes-sync-linux.desktop"
install -m 644 "$ROOT_DIR/assets/linux/notes-sync-linux.svg" \
  "$STAGE_DIR/usr/share/icons/hicolor/scalable/apps/notes-sync-linux.svg"

cat > "$STAGE_DIR/usr/bin/notes-sync-linux" <<'EOF'
#!/usr/bin/env sh
exec /opt/notes-sync-linux/NotesSyncLinux "$@"
EOF
chmod 755 "$STAGE_DIR/usr/bin/notes-sync-linux"

cat > "$STAGE_DIR/DEBIAN/control" <<EOF
Package: notes-sync-linux
Version: ${VERSION}
Section: utils
Priority: optional
Architecture: amd64
Maintainer: NotesSyncLinux Maintainers <noreply@example.com>
Depends: libc6, libx11-6, xdg-utils
Description: Notes sync desktop app for Linux
 Sync public notes files/folders and open files locally.
EOF

dpkg-deb --build --root-owner-group "$STAGE_DIR" "$OUT_DEB"
echo "Built $OUT_DEB"
