from __future__ import annotations

import os


def launch_app() -> None:
    preferred = os.environ.get("NOTES_SYNC_UI", "qt").strip().lower()

    if preferred == "tk":
        from .gui import launch_app as tk_launch

        tk_launch()
        return

    try:
        from .qt_gui import launch_app as qt_launch

        qt_launch()
    except Exception:
        from .gui import launch_app as tk_launch

        tk_launch()


if __name__ == "__main__":
    launch_app()
