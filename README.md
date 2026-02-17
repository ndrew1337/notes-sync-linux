# NotesSyncLinux

Desktop app for Linux that syncs study notes from public links (Yandex Disk, Google Drive, direct URLs).

Repository: [ndrew1337/notes-sync-linux](https://github.com/ndrew1337/notes-sync-linux)

## Features

- Add, edit, delete sources
- Manual sync: selected source or all sources
- Auto-sync timer
- Stop active sync
- Folder mode with tree view (expand/collapse nested folders)
- Sort files inside source folders by `Name` or `Date`
- Double-click file to open
- If file is missing locally, double-click starts download (for Yandex folder sources)
- Keep full folder structure even when some files are skipped/failed
- Filters: `Skip videos`, `Skip > N MB`

## Install (for users)

Download `.deb` or `AppImage` from [Releases](https://github.com/ndrew1337/notes-sync-linux/releases).

### Option 1: `.deb`

```bash
sudo apt install ./notes-sync-linux_<VERSION>_amd64.deb
notes-sync-linux
```

### Option 2: `AppImage`

```bash
chmod +x NotesSyncLinux-<VERSION>-x86_64.AppImage
./NotesSyncLinux-<VERSION>-x86_64.AppImage
```

## Run From Source

### Requirements

- Linux
- Python 3.10+
- `xdg-open`

Install dependencies:

```bash
python3 -m pip install --upgrade pip
python3 -m pip install -r requirements.txt
```

Run:

```bash
python3 -m notes_sync_linux.main
```

Alternative:

```bash
./run.sh
```

## UI

- Qt (`PySide6`) only

Run Qt entrypoint directly:

```bash
python3 -m notes_sync_linux.main_qt
```

## Storage

Local data path:

- `~/.notes-sync-app-linux/config.json`
- `~/.notes-sync-app-linux/sources/`
- `~/.notes-sync-app-linux/pdfs/`

## Link Support

- Yandex public file/folder links (`disk.yandex.ru`, `disk.360.yandex.ru`, `docs.yandex.ru`)
- Google Drive public file links
- Direct HTTP/HTTPS file links

Notes:

- On-demand per-file redownload (double-click missing file) is implemented for Yandex folder sources.
- For non-Yandex providers, per-file on-demand download depends on available remote path metadata.

## Development

Run checks locally:

```bash
python3 -m py_compile notes_sync_linux/core.py notes_sync_linux/gui.py notes_sync_linux/qt_gui.py notes_sync_linux/main.py notes_sync_linux/main_qt.py
PYTHONPATH=. python3 -m unittest discover -s tests -v
PYTHONPATH=. python3 scripts/gui_smoke_test.py
PYTHONPATH=. python3 scripts/gui_smoke_test_qt.py
```

## Release Flow

Automated via GitHub Actions:

- `.github/workflows/linux-notes-sync-ci.yml`
- `.github/workflows/linux-notes-sync-release.yml`

Create a release tag:

```bash
git tag v0.1.2
git push origin v0.1.2
```

Release workflow will:

- run tests and GUI smoke tests
- build `.deb` and `AppImage`
- generate release notes from `CHANGELOG.md`
- publish GitHub Release assets

Manual artifact build:

```bash
./scripts/build_release_artifacts.sh 0.1.2
```

Artifacts appear in `dist/`.

## Troubleshooting

`ImportError: libEGL.so.1` in CI or Linux host:

```bash
sudo apt-get update
sudo apt-get install -y libegl1 libgl1 libxkbcommon-x11-0 libxcb-cursor0
```

Qt issues on specific distro:

- ensure Qt runtime packages are installed and `pip install -r requirements.txt` completed

## Contributing

- Contribution guide: `CONTRIBUTING.md`
- Bug template: `.github/ISSUE_TEMPLATE/linux_notes_sync_bug.yml`
- Changelog: `CHANGELOG.md`

## License

MIT (`LICENSE`)
