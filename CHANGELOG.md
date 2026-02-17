# Changelog

All notable changes to this project will be documented in this file.

The format is based on Keep a Changelog.

## [Unreleased]

## [0.1.1] - 2026-02-17

### Added
- Linux desktop app with folder sync and Finder-like tree navigation.
- On-demand download for missing files by double click.
- GitHub Actions CI for compile/tests.
- Linux release pipeline for `.deb` and `AppImage`.
- New PySide6/Qt interface with modern styling.
- Qt smoke tests in CI and release workflows.

### Changed
- `main` now prefers Qt UI and falls back to tkinter.
- PyInstaller build now packages Qt entrypoint (`main_qt.py`).

## [0.1.0] - 2026-02-17

### Added
- Initial public Linux release.
- Public issue template for bug reports.
- Packaging scripts for `.deb` and `AppImage`.
- Automatic GitHub Release artifacts on `v*` tags.
