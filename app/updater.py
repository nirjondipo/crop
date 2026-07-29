"""Check for updates from GitHub Releases."""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from app.version import GITHUB_REPO, __version__


@dataclass
class UpdateInfo:
    current: str
    latest: str
    notes: str
    download_url: str
    channel: str  # "github" | "none"
    available: bool


def _parse_version(text: str) -> tuple[int, ...]:
    text = text.strip().lstrip("vV")
    parts = re.findall(r"\d+", text)
    if not parts:
        return (0,)
    return tuple(int(p) for p in parts)


def is_newer(latest: str, current: str) -> bool:
    return _parse_version(latest) > _parse_version(current)


def _http_json(url: str, timeout: float = 8.0) -> dict | list | None:
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json, application/json",
            "User-Agent": f"Crop-Updater/{__version__}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError, OSError):
        return None


def check_github() -> UpdateInfo | None:
    data = _http_json(f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest")
    if not isinstance(data, dict) or "tag_name" not in data:
        return None
    if data.get("draft") or data.get("prerelease"):
        return None
    tag = str(data.get("tag_name") or "")
    if not tag:
        return None
    notes = str(data.get("body") or data.get("name") or "").strip()
    download = ""
    for asset in data.get("assets") or []:
        name = str(asset.get("name") or "").lower()
        if name == "cropsetup.exe" or name.endswith("cropsetup.exe"):
            download = str(asset.get("browser_download_url") or "")
            break
    if not download:
        for asset in data.get("assets") or []:
            name = str(asset.get("name") or "").lower()
            if name.endswith(".exe") and "setup" in name:
                download = str(asset.get("browser_download_url") or "")
                break
    if not download:
        return None
    return UpdateInfo(
        current=__version__,
        latest=tag.lstrip("vV"),
        notes=notes[:500],
        download_url=download,
        channel="github",
        available=is_newer(tag, __version__),
    )


def check_for_updates() -> UpdateInfo:
    github = check_github()
    if github is not None:
        return github
    return UpdateInfo(
        current=__version__,
        latest=__version__,
        notes="",
        download_url="",
        channel="none",
        available=False,
    )


def download_file(url: str, dest: Path, on_progress=None) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": f"Crop-Updater/{__version__}"})
    with urllib.request.urlopen(req, timeout=120) as resp, open(dest, "wb") as out:
        total = int(resp.headers.get("Content-Length") or 0)
        read = 0
        while True:
            chunk = resp.read(1024 * 256)
            if not chunk:
                break
            out.write(chunk)
            read += len(chunk)
            if on_progress and total:
                on_progress(read / total)


def launch_installer(setup_path: Path) -> None:
    """Run CropSetup.exe so the user can update over the existing install."""
    if os.name == "nt":
        subprocess.Popen(
            [str(setup_path)],
            cwd=str(setup_path.parent),
            creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,  # type: ignore[attr-defined]
        )
    else:
        win = str(setup_path)
        if win.startswith("/mnt/"):
            drive = win[5].upper()
            rest = win[6:].replace("/", "\\")
            win = f"{drive}:{rest}"
        subprocess.Popen(
            ["powershell.exe", "-NoProfile", "-Command", f"Start-Process -FilePath '{win}'"],
        )


def download_and_install(info: UpdateInfo, on_status=None) -> Path:
    """Download setup to a temp file and launch it. Returns setup path."""
    if not info.download_url:
        raise RuntimeError("No download URL")
    if on_status:
        on_status("Downloading update…")
    tmp = Path(tempfile.gettempdir()) / f"CropSetup-{info.latest}.exe"
    download_file(info.download_url, tmp, on_progress=None)
    if on_status:
        on_status("Opening installer…")
    launch_installer(tmp)
    return tmp


def check_async(callback) -> None:
    def _run():
        try:
            info = check_for_updates()
            callback(info, None)
        except Exception as exc:  # noqa: BLE001
            callback(None, exc)

    threading.Thread(target=_run, daemon=True).start()
