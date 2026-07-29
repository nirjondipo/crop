#!/usr/bin/env python3
"""Local control API for Crop desktop app (start/stop/status).

Listens on 127.0.0.1 only. Started as a systemd --user service so PHP-FPM
(www-data) can start/stop the GUI as the logged-in desktop user.

When the desktop window is closed, status becomes "not running" quickly so
RAM/CPU are not held by a stale "running" state.
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

ROOT = Path(__file__).resolve().parent.parent
PID_FILE = ROOT / ".run" / "app.pid"
LOG_FILE = ROOT / ".run" / "app.log"
VENV_PYTHON = ROOT / ".venv" / "bin" / "python"
MAIN_PY = ROOT / "main.py"
MAIN_MARKER = str(MAIN_PY.resolve())

_lock = threading.Lock()
_proc: subprocess.Popen | None = None
_log_handle = None


def _ensure_run_dir() -> None:
    PID_FILE.parent.mkdir(parents=True, exist_ok=True)


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _is_crop_process(pid: int) -> bool:
    """True only if pid is alive and its cmdline is our crop main.py."""
    if not _pid_alive(pid):
        return False
    cmdline_path = Path(f"/proc/{pid}/cmdline")
    try:
        raw = cmdline_path.read_bytes().replace(b"\x00", b" ").decode("utf-8", "ignore")
    except OSError:
        return False
    return "main.py" in raw and ("crop" in raw.lower() or MAIN_MARKER in raw or "projects/crop" in raw)


def _clear_pid_file() -> None:
    try:
        PID_FILE.unlink(missing_ok=True)
    except OSError:
        pass


def _reap() -> None:
    """Drop stale PID / finished Popen so status never lies after window close."""
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
    return {
        "ok": True,
        "running": pid is not None,
        "pid": pid,
        "app": str(MAIN_PY),
    }


def _start() -> dict:
    global _proc, _log_handle

    existing = _read_pid()
    if existing is not None:
        return {"ok": True, "running": True, "pid": existing, "message": "Already running"}

    if not VENV_PYTHON.is_file():
        return {
            "ok": False,
            "running": False,
            "pid": None,
            "message": "Missing .venv — run: python3 -m venv .venv && pip install -r requirements.txt",
        }
    if not MAIN_PY.is_file():
        return {"ok": False, "running": False, "pid": None, "message": "main.py not found"}

    _ensure_run_dir()
    env = os.environ.copy()
    env.setdefault("DISPLAY", ":0")
    env.setdefault("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    if "DBUS_SESSION_BUS_ADDRESS" not in env:
        bus = Path(env["XDG_RUNTIME_DIR"]) / "bus"
        if bus.exists():
            env["DBUS_SESSION_BUS_ADDRESS"] = f"unix:path={bus}"

    with _lock:
        _log_handle = open(LOG_FILE, "a", encoding="utf-8")  # noqa: SIM115
        _log_handle.write(f"\n--- start {time.strftime('%Y-%m-%d %H:%M:%S')} ---\n")
        _log_handle.flush()

        proc = subprocess.Popen(
            [str(VENV_PYTHON), str(MAIN_PY)],
            cwd=str(ROOT),
            env=env,
            stdout=_log_handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        _proc = proc
        PID_FILE.write_text(str(proc.pid), encoding="utf-8")

    time.sleep(0.35)
    if proc.poll() is not None:
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
            "message": "App exited immediately. Is python3-tk installed?",
            "log": tail,
        }

    return {"ok": True, "running": True, "pid": proc.pid, "message": "Started"}


def _kill_pid(pid: int) -> None:
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
    """Called by the desktop app when the window is closed — mark stopped immediately."""
    global _proc, _log_handle
    current = None
    if PID_FILE.exists():
        try:
            current = int(PID_FILE.read_text(encoding="utf-8").strip())
        except (ValueError, OSError):
            current = None

    # Trust the app: clear tracking so the web UI shows Stopped right away.
    # Do not kill here — the window close handler is still exiting cleanly.
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
    # Clear stale lock from previous boot
    _reap()
    threading.Thread(target=_watchdog_loop, name="crop-reap", daemon=True).start()
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Crop control listening on http://{HOST}:{PORT}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
