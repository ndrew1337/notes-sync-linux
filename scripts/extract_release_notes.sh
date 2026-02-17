#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <version> [changelog_path] [output_path]" >&2
  exit 1
fi

VERSION="$1"
CHANGELOG_PATH="${2:-CHANGELOG.md}"
OUTPUT_PATH="${3:-dist/RELEASE_NOTES.md}"

mkdir -p "$(dirname "$OUTPUT_PATH")"

if [[ ! -f "$CHANGELOG_PATH" ]]; then
  cat > "$OUTPUT_PATH" <<EOF
## NotesSyncLinux ${VERSION}

Release built automatically.
Changelog file is missing in this revision.
EOF
  exit 0
fi

TMP_SECTION="$(mktemp)"

awk -v version="$VERSION" '
  BEGIN { capture = 0 }
  $0 ~ "^## \\[" version "\\]" {
    capture = 1
    next
  }
  capture == 1 && $0 ~ "^## \\[" {
    exit
  }
  capture == 1 {
    print
  }
' "$CHANGELOG_PATH" > "$TMP_SECTION"

if [[ -s "$TMP_SECTION" ]]; then
  {
    echo "## NotesSyncLinux ${VERSION}"
    echo
    cat "$TMP_SECTION"
  } > "$OUTPUT_PATH"
else
  cat > "$OUTPUT_PATH" <<EOF
## NotesSyncLinux ${VERSION}

No explicit section found in \`${CHANGELOG_PATH}\` for version \`${VERSION}\`.
See commit history for this release.
EOF
fi

rm -f "$TMP_SECTION"
