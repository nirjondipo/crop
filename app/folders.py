"""Folder/file pickers that prefer the Windows native dialog when running under WSL."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

# Shared PowerShell preamble: invisible TopMost owner so dialogs appear ABOVE WSLg windows.
_PS_OWNER = r"""
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$owner = New-Object System.Windows.Forms.Form
$owner.Text = 'Crop'
$owner.StartPosition = 'CenterScreen'
$owner.Size = New-Object System.Drawing.Size(1, 1)
$owner.Opacity = 0
$owner.ShowInTaskbar = $false
$owner.TopMost = $true
$owner.FormBorderStyle = 'None'
$owner.Show()
$owner.Activate()
$owner.BringToFront()
[System.Windows.Forms.Application]::DoEvents()
Start-Sleep -Milliseconds 80
"""

_PS_OWNER_CLOSE = r"""
$owner.Hide()
$owner.Close()
$owner.Dispose()
"""


def is_wsl() -> bool:
    if os.environ.get("WSL_DISTRO_NAME") or os.environ.get("WSL_INTEROP"):
        return True
    try:
        return "microsoft" in Path("/proc/version").read_text(encoding="utf-8").lower()
    except OSError:
        return False


def windows_to_wsl(path: str) -> Path:
    """Convert ``C:\\Users\\...`` → ``/mnt/c/Users/...``."""
    path = path.strip().strip('"').replace("/", "\\")
    m = re.match(r"^([A-Za-z]):\\(.*)$", path)
    if not m:
        return Path(path)
    drive, rest = m.group(1).lower(), m.group(2).replace("\\", "/")
    return Path(f"/mnt/{drive}/{rest}") if rest else Path(f"/mnt/{drive}")


def wsl_to_windows(path: str | Path) -> str:
    """Convert ``/mnt/c/Users/...`` → ``C:\\Users\\...`` when possible."""
    p = Path(path).as_posix()
    m = re.match(r"^/mnt/([a-zA-Z])(/.*)?$", p)
    if not m:
        return str(path)
    drive = m.group(1).upper()
    rest = (m.group(2) or "").replace("/", "\\")
    return f"{drive}:{rest}" if rest else f"{drive}:\\"


def default_windows_start() -> str:
    """Best starting folder for the Windows picker."""
    for cmd in (
        ['powershell.exe', '-NoProfile', '-Command', '[Environment]::GetFolderPath("MyPictures")'],
        ['powershell.exe', '-NoProfile', '-Command', '[Environment]::GetFolderPath("UserProfile")'],
    ):
        try:
            out = subprocess.check_output(cmd, text=True, timeout=8, stderr=subprocess.DEVNULL)
            value = out.strip().splitlines()[-1].strip().strip("\r")
            if value and re.match(r"^[A-Za-z]:\\", value):
                return value
        except (OSError, subprocess.SubprocessError):
            continue
    return r"C:\Users"


def _powershell_bin() -> str | None:
    for name in ("powershell.exe", "pwsh.exe"):
        found = shutil.which(name)
        if found:
            return found
    candidate = Path("/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe")
    if candidate.is_file():
        return str(candidate)
    return None


def _q(s: str) -> str:
    return s.replace("'", "''")


def _run_ps(script: str) -> subprocess.CompletedProcess[str] | None:
    ps = _powershell_bin()
    if not ps:
        return None
    try:
        return subprocess.run(
            [ps, "-STA", "-NoProfile", "-WindowStyle", "Hidden", "-Command", script],
            capture_output=True,
            text=True,
            timeout=300,
        )
    except (OSError, subprocess.SubprocessError):
        return None


def pick_folder_windows(title: str = "Select folder", initial: str | None = None) -> str | None:
    """Open the native Windows folder dialog on top. Returns a Windows path or None."""
    start = initial or default_windows_start()
    if start.startswith("/mnt/"):
        start = wsl_to_windows(start)

    script = f"""
{_PS_OWNER}
$dialog = New-Object System.Windows.Forms.FolderBrowserDialog
$dialog.Description = '{_q(title)}'
$dialog.ShowNewFolderButton = $true
try {{ $dialog.SelectedPath = '{_q(start)}' }} catch {{}}
$dialog.RootFolder = [Environment+SpecialFolder]::MyComputer
$res = $dialog.ShowDialog($owner)
{_PS_OWNER_CLOSE}
if ($res -eq [System.Windows.Forms.DialogResult]::OK) {{
    Write-Output $dialog.SelectedPath
}}
"""
    result = _run_ps(script)
    if result is None:
        return None

    lines = [ln.strip().strip("\r") for ln in (result.stdout or "").splitlines() if ln.strip()]
    if not lines:
        return None
    chosen = lines[-1]
    if not re.match(r"^[A-Za-z]:\\", chosen):
        return None
    return chosen


def pick_folder(title: str = "Select folder", initial_linux: str | None = None) -> tuple[str, Path] | None:
    """
    Pick a folder.

    On WSL: native Windows dialog. Returns ``(display_windows_path, linux_path)``.
    Elsewhere: Tk dialog. Returns ``(linux_path_str, Path)``.
    """
    if is_wsl() and _powershell_bin():
        initial_win = wsl_to_windows(initial_linux) if initial_linux else None
        chosen = pick_folder_windows(title=title, initial=initial_win)
        if not chosen:
            return None
        return chosen, windows_to_wsl(chosen)

    from tkinter import filedialog

    start = initial_linux
    if not start:
        start = "/mnt/c/Users" if Path("/mnt/c/Users").is_dir() else str(Path.home())
    chosen = filedialog.askdirectory(title=title, initialdir=start)
    if not chosen:
        return None
    return chosen, Path(chosen)


def pick_files_windows(
    title: str = "Select images",
    initial: str | None = None,
) -> list[str] | None:
    """Native Windows multi-select file dialog on top. Returns Windows paths or None."""
    start = initial or default_windows_start()
    if start.startswith("/mnt/"):
        start = wsl_to_windows(start)
    if re.match(r"^[A-Za-z]:\\", start):
        leaf = start.rstrip("\\").split("\\")[-1]
        if "." in leaf and not start.endswith("\\"):
            start = "\\".join(start.rstrip("\\").split("\\")[:-1]) or start

    script = f"""
{_PS_OWNER}
$dialog = New-Object System.Windows.Forms.OpenFileDialog
$dialog.Title = '{_q(title)}'
$dialog.Multiselect = $true
$dialog.CheckFileExists = $true
$dialog.Filter = 'Images (*.jpg;*.jpeg;*.png;*.webp;*.bmp;*.tif;*.tiff)|*.jpg;*.jpeg;*.png;*.webp;*.bmp;*.tif;*.tiff;*.JPG;*.JPEG;*.PNG;*.WEBP;*.BMP;*.TIF;*.TIFF|All files (*.*)|*.*'
try {{ $dialog.InitialDirectory = '{_q(start)}' }} catch {{}}
$res = $dialog.ShowDialog($owner)
{_PS_OWNER_CLOSE}
if ($res -eq [System.Windows.Forms.DialogResult]::OK) {{
    $dialog.FileNames | ForEach-Object {{ Write-Output $_ }}
}}
"""
    result = _run_ps(script)
    if result is None:
        return None

    paths = [ln.strip().strip("\r") for ln in (result.stdout or "").splitlines() if ln.strip()]
    paths = [p for p in paths if re.match(r"^[A-Za-z]:\\", p)]
    return paths or None


def pick_files(
    title: str = "Select images",
    initial_linux: str | None = None,
) -> list[tuple[str, Path]] | None:
    """
    Pick one or more image files.

    Returns list of ``(display_path, linux_path)`` or None if cancelled.
    """
    if is_wsl() and _powershell_bin():
        initial_win = wsl_to_windows(initial_linux) if initial_linux else None
        chosen = pick_files_windows(title=title, initial=initial_win)
        if not chosen:
            return None
        return [(p, windows_to_wsl(p)) for p in chosen]

    from tkinter import filedialog

    start = initial_linux
    if not start:
        start = "/mnt/c/Users" if Path("/mnt/c/Users").is_dir() else str(Path.home())
    chosen = filedialog.askopenfilenames(
        title=title,
        initialdir=start,
        filetypes=[
            ("Images", "*.jpg *.jpeg *.png *.webp *.bmp *.tif *.tiff"),
            ("All files", "*.*"),
        ],
    )
    if not chosen:
        return None
    return [(p, Path(p)) for p in chosen]


def normalize_path(path_str: str) -> Path:
    """
    Normalize a path typed or pasted into the UI.

    - Native Windows: keep ``B:/Work/...`` / ``B:\\Work\\...`` as a real Windows Path
    - WSL: convert Windows paths to ``/mnt/b/Work/...``
    """
    text = path_str.strip().strip('"').strip("'")
    if not text:
        return Path(text)

    # Drive-letter path (Windows style)
    if re.match(r"^[A-Za-z]:[\\/]", text):
        if os.name == "nt":
            # Native Windows exe — do NOT map to /mnt/...
            return Path(text)
        if is_wsl():
            return windows_to_wsl(text)
        return Path(text)

    # Accidentally saved WSL path while running on Windows
    if os.name == "nt":
        m = re.match(r"^[/\\]mnt[/\\]([a-zA-Z])[/\\]?(.*)$", text.replace("\\", "/"))
        if m:
            drive = m.group(1).upper()
            rest = (m.group(2) or "").replace("/", "\\")
            return Path(f"{drive}:\\{rest}" if rest else f"{drive}:\\")

    return Path(text)


def normalize_to_linux(path_str: str) -> Path:
    """Backward-compatible alias for ``normalize_path``."""
    return normalize_path(path_str)


def open_in_explorer(path: Path) -> bool:
    """Open a folder in the system file manager. Returns True on success."""
    try:
        target = path if path.is_dir() else path.parent
        if not target.exists():
            return False
        if os.name == "nt":
            os.startfile(str(target))  # type: ignore[attr-defined]
            return True
        if is_wsl() and _powershell_bin():
            win = wsl_to_windows(str(target))
            if win:
                subprocess.Popen(
                    ["explorer.exe", win],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                return True
        opener = shutil.which("xdg-open") or shutil.which("open")
        if opener:
            subprocess.Popen(
                [opener, str(target)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return True
    except OSError:
        return False
    return False
