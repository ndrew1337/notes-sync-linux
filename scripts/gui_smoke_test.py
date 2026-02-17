from __future__ import annotations

import os
import tempfile

os.environ["HOME"] = tempfile.mkdtemp(prefix="notes-sync-home-")

from notes_sync_linux.gui import NotesSyncLinuxApp  # noqa: E402


def main() -> None:
    app = NotesSyncLinuxApp()
    app.update_idletasks()
    app.after(50, app.destroy)
    app.mainloop()
    print("GUI smoke test passed")


if __name__ == "__main__":
    main()
