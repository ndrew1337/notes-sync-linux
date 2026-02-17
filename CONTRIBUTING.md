# Contributing

## Bug Reports

Please use the GitHub issue form:

- `.github/ISSUE_TEMPLATE/linux_notes_sync_bug.yml`

Include:

- Linux distro and version
- Exact steps to reproduce
- Expected result and actual result
- Full traceback/log if available
- Commit hash or release version

## Local Validation

```bash
cd /Users/andrew/.codex/workspaces/default/notes_sync_app_linux
python3 -m py_compile notes_sync_linux/core.py notes_sync_linux/gui.py notes_sync_linux/qt_gui.py notes_sync_linux/main.py notes_sync_linux/main_qt.py
PYTHONPATH=. python3 -m unittest discover -s tests -v
PYTHONPATH=. python3 scripts/gui_smoke_test_qt.py
```

## Release Flow

1. Push changes to `main`.
2. Update `CHANGELOG.md` and add a section for new version (for example `## [0.1.1] - 2026-02-20`).
3. Create and push a version tag:

```bash
git tag v0.1.0
git push origin v0.1.0
```

This triggers `.github/workflows/linux-notes-sync-release.yml`, runs tests + GUI smoke test, and publishes `.deb` + `AppImage` in GitHub Releases.
