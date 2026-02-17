# NotesSyncLinux

Linux desktop version of the notes sync app (Tkinter, Python 3.10+).

## Features

- Add/edit/delete note sources (public links)
- Sync selected / sync all
- Stop sync
- Folder mode for Yandex public folders
- Finder-like tree for folder files (nested folders, expand/collapse)
- Double-click on file:
  - opens local file if already downloaded
  - starts download if file is missing locally, then opens it
- Partial sync behavior:
  - all file entries remain visible in tree
  - skipped/failed files are not removed from structure
- Filters:
  - `Skip videos`
  - `Skip > N MB`

## Requirements

- Linux
- Python 3.10+
- `tkinter` package (on Debian/Ubuntu: `sudo apt install python3-tk`)
- `xdg-open` (usually preinstalled)

## Run

```bash
cd notes_sync_app_linux
python3 -m notes_sync_linux.main
```

or:

```bash
cd notes_sync_app_linux
./run.sh
```

## Storage

App data is stored in:

- `~/.notes-sync-app-linux/config.json`
- `~/.notes-sync-app-linux/sources/`
- `~/.notes-sync-app-linux/pdfs/`

## Notes

- On-demand file download by double-click is implemented for Yandex folder sources.
- For non-Yandex sources, on-demand per-file download is not guaranteed because remote path metadata is provider-specific.

## Publish To GitHub

1. Create a new empty repository on GitHub, for example `notes-sync-linux`.
2. From local terminal:

```bash
cd /Users/andrew/.codex/workspaces/default/notes_sync_app_linux
git init
git add .
git commit -m "Initial Linux version"
git branch -M main
git remote add origin git@github.com:<YOUR_USERNAME>/notes-sync-linux.git
git push -u origin main
```

After push:

- GitHub Actions workflow (`.github/workflows/linux-notes-sync-ci.yml`) will run tests on Ubuntu automatically.
- Users will get a structured bug form from `.github/ISSUE_TEMPLATE/linux_notes_sync_bug.yml`.
- Contribution notes are in `CONTRIBUTING.md`.
- License: `LICENSE` (MIT).

## Update After Changes

```bash
cd /Users/andrew/.codex/workspaces/default/notes_sync_app_linux
git add .
git commit -m "Describe changes"
git push
```

## Release Artifacts

The repository includes automated Linux packaging:

- `.deb` package
- `AppImage`
- `SHA256SUMS.txt`

Workflow file:

- `.github/workflows/linux-notes-sync-release.yml`

### Automatic release on tag

Push a tag like `v0.1.0`:

```bash
cd /Users/andrew/.codex/workspaces/default/notes_sync_app_linux
git tag v0.1.0
git push origin v0.1.0
```

GitHub Actions will:

- run compile/tests
- run GUI smoke test in virtual display (`xvfb`)
- build `.deb` and `AppImage`
- extract release notes from `CHANGELOG.md` section `[0.1.0]`
- create a GitHub Release with artifacts attached

### Manual build on Linux

Install build dependencies:

```bash
sudo apt-get update
sudo apt-get install -y python3 python3-pip python3-tk dpkg-dev desktop-file-utils patchelf squashfs-tools
python3 -m pip install --upgrade pip
python3 -m pip install pyinstaller
```

Build all artifacts:

```bash
cd /Users/andrew/.codex/workspaces/default/notes_sync_app_linux
./scripts/build_release_artifacts.sh 0.1.0
```

Artifacts will appear in `dist/`.

## Changelog

Release notes are generated from `CHANGELOG.md`.

- Add new changes to `## [Unreleased]`.
- Before tagging, move them into a new section like `## [0.1.1] - YYYY-MM-DD`.
