"""Resolve bundled asset paths (dev tree or PyInstaller)."""

from __future__ import annotations

import sys
from pathlib import Path


def app_dir() -> Path:
    """Directory that holds app package files (icons, etc.)."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        # onefile extracts to _MEIPASS; we ship icons under app/
        base = Path(sys._MEIPASS)  # type: ignore[attr-defined]
        bundled = base / "app"
        if bundled.is_dir():
            return bundled
        return base
    return Path(__file__).resolve().parent


def asset_path(*parts: str) -> Path | None:
    path = app_dir().joinpath(*parts)
    return path if path.is_file() else None
