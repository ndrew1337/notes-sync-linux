#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <version>" >&2
  exit 1
fi

VERSION="$1"
ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

mkdir -p dist

"$ROOT_DIR/scripts/build_pyinstaller.sh"
"$ROOT_DIR/scripts/build_deb.sh" "$VERSION"
"$ROOT_DIR/scripts/build_appimage.sh" "$VERSION"

cd "$ROOT_DIR/dist"
if command -v sha256sum >/dev/null 2>&1; then
  sha256sum ./*.deb ./*.AppImage > SHA256SUMS.txt
else
  shasum -a 256 ./*.deb ./*.AppImage > SHA256SUMS.txt
fi

echo "Artifacts in $ROOT_DIR/dist"
