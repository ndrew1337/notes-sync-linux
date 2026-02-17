from __future__ import annotations

def launch_app() -> None:
    try:
        from .qt_gui import launch_app as qt_launch
    except Exception as exc:
        raise RuntimeError("Qt UI is required. Install dependencies with: python3 -m pip install -r requirements.txt") from exc
    qt_launch()


if __name__ == "__main__":
    launch_app()
