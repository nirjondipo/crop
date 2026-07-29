#!/usr/bin/env python3
"""Local control API for Crop desktop app (start/stop/status).

Listens on 127.0.0.1:18765. Works on Windows (native install) and WSL.
When a Windows install exists, WSL control prefers launching that native app
(much faster UI than Tk under WSLg).
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HOST = "127.0.0.1"
PORT = 18765

IS_WINDOWS = os.name == "nt"
FROZEN = getattr(sys, "frozen", False)


def _runtime_root() -> Path:
    if FROZEN:
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


ROOT = _runtime_root()
PID_FILE = ROOT / ".run" / "app.pid"
LOG_FILE = ROOT / ".run" / "app.log"

_lock = threading.Lock()
_proc: subprocess.Popen | None = None
_log_handle = None


def _venv_python() -> Path:
    if IS_WINDOWS:
        # Installed Setup places Crop.exe next to CropControl.exe
        exe = ROOT / "Crop.exe"
        if exe.is_file():
            return exe
        w = ROOT / ".venv" / "Scripts" / "pythonw.exe"
        if w.is_file():
            return w
        return ROOT / ".venv" / "Scripts" / "python.exe"
    return ROOT / ".venv" / "bin" / "python"


def _main_py() -> Path:
    # Frozen GUI is Crop.exe; script mode uses main.py
    if IS_WINDOWS and (ROOT / "Crop.exe").is_file():
        return ROOT / "Crop.exe"
    return ROOT / "main.py"


def _windows_install_root() -> Path | None:
    """If running under WSL, return the native Windows install folder if present."""
    if IS_WINDOWS:
        if (ROOT / "Crop.exe").is_file() or (ROOT / "install.json").is_file():
            return ROOT
        return None
    # Discover via PowerShell LOCALAPPDATA
    try:
        out = subprocess.check_output(
            [
                "powershell.exe",
                "-NoProfile",
                "-Command",
                "Write-Output $env:LOCALAPPDATA",
            ],
            text=True,
            timeout=5,
            stderr=subprocess.DEVNULL,
        )
        local = out.strip().splitlines()[-1].strip().strip("\r")
        if local and len(local) > 3:
            drive = local[0].lower()
            rest = local[2:].replace("\\", "/").lstrip("/")
            candidate = Path(f"/mnt/{drive}/{rest}/Crop")
            try:
                if (candidate / "install.json").is_file() or (candidate / "Crop.exe").is_file():
                    return candidate
            except OSError:
                pass
    except (OSError, subprocess.SubprocessError, IndexError):
        pass
    # Fallback common path
    try:
        users = Path("/mnt/c/Users")
        if users.is_dir():
            for user in users.iterdir():
                try:
                    candidate = user / "AppData" / "Local" / "Crop"
                    if (candidate / "install.json").is_file() or (candidate / "Crop.exe").is_file():
                        return candidate
                except OSError:
                    continue
    except OSError:
        pass
    return None


def _launch_target() -> tuple[Path, Path, list[str]]:
    """
    Return (cwd, executable, argv) for the app to launch.
    Prefer native Windows Crop.exe from Setup install.
    """
    win_root = _windows_install_root()
    if win_root is not None:
        exe = win_root / "Crop.exe"
        meta_exe = None
        try:
            meta = json.loads((win_root / "install.json").read_text(encoding="utf-8"))
            if meta.get("exe"):
                # May be a Windows path string when read from WSL — keep for PowerShell start
                meta_exe = meta["exe"]
        except (OSError, json.JSONDecodeError, TypeError):
            pass
        if exe.is_file():
            return win_root, exe, [str(exe)]
        if meta_exe:
            return win_root, Path(meta_exe), [meta_exe]
    py = _venv_python()
    main = _main_py()
    if main.suffix.lower() == ".exe":
        return ROOT, main, [str(main)]
    return ROOT, py, [str(py), str(main)]


def _ensure_run_dir() -> None:
    PID_FILE.parent.mkdir(parents=True, exist_ok=True)


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if IS_WINDOWS:
        try:
            out = subprocess.check_output(
                ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                text=True,
                stderr=subprocess.DEVNULL,
                timeout=5,
            )
            return str(pid) in out and "INFO:" not in out
        except (OSError, subprocess.SubprocessError):
            return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _is_crop_process(pid: int) -> bool:
    if not _pid_alive(pid):
        return False
    if IS_WINDOWS:
        try:
            out = subprocess.check_output(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-Command",
                    f"(Get-CimInstance Win32_Process -Filter \"ProcessId={pid}\").CommandLine",
                ],
                text=True,
                timeout=5,
                stderr=subprocess.DEVNULL,
            )
            raw = out.lower()
            return ("main.py" in raw and "crop" in raw) or "crop.exe" in raw
        except (OSError, subprocess.SubprocessError):
            return _pid_alive(pid)
    try:
        raw = (
            Path(f"/proc/{pid}/cmdline")
            .read_bytes()
            .replace(b"\x00", b" ")
            .decode("utf-8", "ignore")
            .lower()
        )
    except OSError:
        return False
    return ("main.py" in raw and "crop" in raw) or "crop.exe" in raw


def _clear_pid_file() -> None:
    try:
        PID_FILE.unlink(missing_ok=True)
    except OSError:
        pass


def _reap() -> None:
    global _proc, _log_handle
    with _lock:
        if _proc is not None and _proc.poll() is not None:
            _proc = None
            if _log_handle is not None:
                try:
                    _log_handle.close()
                except OSError:
                    pass
                _log_handle = None
            _clear_pid_file()
            return

        if not PID_FILE.exists():
            return
        try:
            pid = int(PID_FILE.read_text(encoding="utf-8").strip())
        except (ValueError, OSError):
            _clear_pid_file()
            return
        if not _is_crop_process(pid):
            _clear_pid_file()
            if _proc is not None and (_proc.pid == pid or _proc.poll() is not None):
                _proc = None


def _read_pid() -> int | None:
    _reap()
    if not PID_FILE.exists():
        return None
    try:
        pid = int(PID_FILE.read_text(encoding="utf-8").strip())
    except (ValueError, OSError):
        return None
    if not _is_crop_process(pid):
        _clear_pid_file()
        return None
    return pid


def _status() -> dict:
    pid = _read_pid()
    cwd, exe, argv = _launch_target()
    return {
        "ok": True,
        "running": pid is not None,
        "pid": pid,
        "app": str(argv[-1] if argv else exe),
        "native_windows": (not IS_WINDOWS and _windows_install_root() is not None)
        or (IS_WINDOWS and (ROOT / "Crop.exe").is_file()),
        "install_root": str(cwd),
    }


def _to_win_path(path: Path | str) -> str:
    text = str(path)
    if text.startswith("/mnt/") and len(text) > 6 and text[5] == "/":
        drive = text[5].upper()
        rest = text[6:].replace("/", "\\")
        return f"{drive}:{rest}"
    return text


def _start() -> dict:
    global _proc, _log_handle

    existing = _read_pid()
    if existing is not None:
        return {"ok": True, "running": True, "pid": existing, "message": "Already running"}

    cwd, exe, argv = _launch_target()
    # exe may be a Windows path string inside Path when from install.json — check carefully
    exe_ok = False
    try:
        exe_ok = Path(exe).is_file()
    except OSError:
        exe_ok = False
    if not exe_ok and not (isinstance(argv, list) and argv and str(argv[0]).lower().endswith(".exe")):
        return {
            "ok": False,
            "running": False,
            "pid": None,
            "message": (
                "App not installed. Build/install with:\n"
                "  powershell -ExecutionPolicy Bypass -File scripts\\windows\\build-installer.ps1\n"
                "then run dist\\CropSetup.exe"
            ),
        }

    _ensure_run_dir()
    env = os.environ.copy()
    use_windows_app = (not IS_WINDOWS and _windows_install_root() is not None) or (
        IS_WINDOWS and str(argv[0]).lower().endswith("crop.exe")
    )

    with _lock:
        _log_handle = open(LOG_FILE, "a", encoding="utf-8")  # noqa: SIM115
        _log_handle.write(
            f"\n--- start {time.strftime('%Y-%m-%d %H:%M:%S')} "
            f"windows_app={use_windows_app} argv={argv!r} ---\n"
        )
        _log_handle.flush()

        if not IS_WINDOWS and _windows_install_root() is not None:
            win_cwd = _to_win_path(cwd)
            win_exe = None
            try:
                meta = json.loads((cwd / "install.json").read_text(encoding="utf-8"))
                win_cwd = meta.get("installRoot") or win_cwd
                win_exe = meta.get("exe")
            except (OSError, json.JSONDecodeError, TypeError):
                pass
            if not win_exe:
                win_exe = _to_win_path(argv[0])
            # Crop.exe takes no args
            ps = (
                f"Start-Process -FilePath '{win_exe}' "
                f"-WorkingDirectory '{win_cwd}' -PassThru | "
                f"Select-Object -ExpandProperty Id"
            )
            try:
                out = subprocess.check_output(
                    ["powershell.exe", "-NoProfile", "-Command", ps],
                    text=True,
                    timeout=15,
                )
                pid = int(out.strip().splitlines()[-1].strip())
                PID_FILE.write_text(str(pid), encoding="utf-8")
                _proc = None
                return {
                    "ok": True,
                    "running": True,
                    "pid": pid,
                    "message": "Started (Windows native)",
                }
            except (OSError, subprocess.SubprocessError, ValueError) as exc:
                return {
                    "ok": False,
                    "running": False,
                    "pid": None,
                    "message": f"Failed to start Windows app: {exc}",
                }

        popen_kwargs: dict = {}
        if IS_WINDOWS:
            popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
        else:
            popen_kwargs["start_new_session"] = True
            env.setdefault("DISPLAY", ":0")
            env.setdefault("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")

        proc = subprocess.Popen(
            argv,
            cwd=str(cwd),
            env=env,
            stdout=_log_handle,
            stderr=subprocess.STDOUT,
            **popen_kwargs,
        )
        _proc = proc
        PID_FILE.write_text(str(proc.pid), encoding="utf-8")

    time.sleep(0.4)
    if _proc is not None and _proc.poll() is not None:
        with _lock:
            _proc = None
            if _log_handle is not None:
                try:
                    _log_handle.close()
                except OSError:
                    pass
                _log_handle = None
        _clear_pid_file()
        tail = ""
        try:
            tail = LOG_FILE.read_text(encoding="utf-8")[-800:]
        except OSError:
            pass
        return {
            "ok": False,
            "running": False,
            "pid": None,
            "message": "App exited immediately.",
            "log": tail,
        }

    return {
        "ok": True,
        "running": True,
        "pid": int(PID_FILE.read_text().strip()),
        "message": "Started",
    }


def _kill_pid(pid: int) -> None:
    if IS_WINDOWS or _windows_install_root() is not None:
        try:
            subprocess.run(
                ["taskkill.exe", "/PID", str(pid), "/T", "/F"],
                capture_output=True,
                timeout=10,
            )
        except (OSError, subprocess.SubprocessError):
            pass
        return

    try:
        os.killpg(pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    except PermissionError:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            return

    deadline = time.time() + 2.0
    while time.time() < deadline:
        if not _pid_alive(pid):
            return
        time.sleep(0.05)
    try:
        os.killpg(pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def _stop() -> dict:
    global _proc, _log_handle
    pid = _read_pid()
    if pid is None:
        with _lock:
            _proc = None
        _clear_pid_file()
        return {"ok": True, "running": False, "pid": None, "message": "Not running"}

    _kill_pid(pid)
    with _lock:
        _proc = None
        if _log_handle is not None:
            try:
                _log_handle.close()
            except OSError:
                pass
            _log_handle = None
    _clear_pid_file()
    return {"ok": True, "running": False, "pid": None, "message": "Stopped"}


def _exited(reported_pid: int | None = None) -> dict:
    global _proc, _log_handle
    current = None
    if PID_FILE.exists():
        try:
            current = int(PID_FILE.read_text(encoding="utf-8").strip())
        except (ValueError, OSError):
            current = None

    if reported_pid is None or current is None or reported_pid == current:
        with _lock:
            _proc = None
            if _log_handle is not None:
                try:
                    _log_handle.close()
                except OSError:
                    pass
                _log_handle = None
        _clear_pid_file()
        return {"ok": True, "running": False, "pid": None, "message": "Marked stopped"}
    return _status()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def _json(self, code: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path in ("/", "/status", "/health"):
            self._json(200, _status())
            return
        self._json(404, {"ok": False, "message": "Not found"})

    def do_POST(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""

        if path == "/start":
            result = _start()
            self._json(200 if result.get("ok") else 500, result)
            return
        if path == "/stop":
            self._json(200, _stop())
            return
        if path == "/exited":
            reported = None
            if body:
                try:
                    payload = json.loads(body.decode("utf-8"))
                    if isinstance(payload, dict) and payload.get("pid") is not None:
                        reported = int(payload["pid"])
                except (ValueError, TypeError, json.JSONDecodeError):
                    reported = None
            self._json(200, _exited(reported))
            return
        self._json(404, {"ok": False, "message": "Not found"})


def _watchdog_loop() -> None:
    while True:
        try:
            _reap()
        except Exception:  # noqa: BLE001
            pass
        time.sleep(1.0)


def main() -> None:
    _ensure_run_dir()
    _reap()
    threading.Thread(target=_watchdog_loop, name="crop-reap", daemon=True).start()
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    mode = "Windows" if IS_WINDOWS else (
        "WSL→Windows native" if _windows_install_root() else "WSL"
    )
    print(f"Crop control listening on http://{HOST}:{PORT} ({mode})", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
