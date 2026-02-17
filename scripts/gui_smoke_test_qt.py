from __future__ import annotations

import os
import tempfile

os.environ["HOME"] = tempfile.mkdtemp(prefix="notes-sync-home-")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from notes_sync_linux.qt_gui import NotesSyncQtWindow  # noqa: E402


def main() -> None:
    app = QApplication.instance() or QApplication([])
    window = NotesSyncQtWindow()
    window.show()
    QTimer.singleShot(150, window.close)
    QTimer.singleShot(200, app.quit)
    app.exec()
    print("Qt GUI smoke test passed")


if __name__ == "__main__":
    main()
