"""Manage Relapse-Exploit local HTTP host for the PS5 browser stage."""

from __future__ import annotations

import os
import socket
import subprocess
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.request import urlretrieve
import zipfile
import tempfile
import shutil

try:
    from desk_common import app_root as _app_root

    ROOT = _app_root()
except Exception:
    ROOT = Path(__file__).resolve().parent
DEFAULT_DIR = ROOT / "vendor" / "Relapse-Exploit"
DEFAULT_PORT = 8000
REPO_ZIP = "https://github.com/ntfargo/Relapse-Exploit/archive/refs/heads/main.zip"

_lock = threading.Lock()
_server: Optional[ThreadingHTTPServer] = None
_thread: Optional[threading.Thread] = None
_serve_dir: Optional[Path] = None
_port = DEFAULT_PORT
_started_at = 0.0
_last_error = ""


def local_ip(prefer_host: str = "") -> str:
    """Best-effort LAN IP (Mac / Windows / Linux)."""
    try:
        from desk_common import local_ip as _local_ip

        return _local_ip(prefer_host)
    except Exception:
        pass
    # Minimal fallback if desk_common unavailable
    if prefer_host:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.connect((prefer_host, 1337))
            ip = sock.getsockname()[0]
            sock.close()
            if ip and not ip.startswith("127."):
                return ip
        except OSError:
            pass
    return "127.0.0.1"


def relapse_ready(path: Optional[Path] = None) -> bool:
    directory = Path(path or DEFAULT_DIR)
    return (directory / "index.html").is_file()


def ensure_relapse(path: Optional[Path] = None) -> Path:
    directory = Path(path or DEFAULT_DIR)
    if relapse_ready(directory):
        return directory
    directory.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="relapse-") as tmp:
        tmp_path = Path(tmp)
        zip_path = tmp_path / "relapse.zip"
        urlretrieve(REPO_ZIP, zip_path)
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(tmp_path)
        extracted = next(tmp_path.glob("Relapse-Exploit-*"), None)
        if not extracted or not (extracted / "index.html").is_file():
            raise RuntimeError("Archive Relapse invalide (index.html manquant)")
        if directory.exists():
            shutil.rmtree(directory)
        shutil.move(str(extracted), str(directory))
    if not relapse_ready(directory):
        raise RuntimeError("Installation Relapse échouée")
    return directory


class _QuietHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, directory: str = "", **kwargs):
        super().__init__(*args, directory=directory, **kwargs)

    def log_message(self, *_args):
        return

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        super().end_headers()


def is_running() -> bool:
    with _lock:
        return _server is not None


def status(console_host: str = "") -> Dict[str, Any]:
    ip = local_ip(console_host)
    with _lock:
        running = _server is not None
        port = _port
        directory = str(_serve_dir or DEFAULT_DIR)
        err = _last_error
        started = _started_at
    return {
        "running": running,
        "ready": relapse_ready(Path(directory)),
        "directory": directory,
        "port": port,
        "pc_ip": ip,
        "url": f"http://{ip}:{port}/",
        "repo": "https://github.com/ntfargo/Relapse-Exploit",
        "started_at": started,
        "error": err,
    }


def start(console_host: str = "", port: int = DEFAULT_PORT, directory: Optional[str] = None) -> Dict[str, Any]:
    global _server, _thread, _serve_dir, _port, _started_at, _last_error
    directory_path = ensure_relapse(Path(directory) if directory else DEFAULT_DIR)
    port = int(port or DEFAULT_PORT)

    with _lock:
        if _server is not None:
            return status(console_host)
        try:
            handler = lambda *a, **k: _QuietHandler(*a, directory=str(directory_path), **k)
            server = ThreadingHTTPServer(("0.0.0.0", port), handler)
            server.daemon_threads = True
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            _server = server
            _thread = thread
            _serve_dir = directory_path
            _port = port
            _started_at = time.time()
            _last_error = ""
        except OSError as exc:
            _last_error = str(exc)
            raise RuntimeError(f"Impossible de démarrer Relapse sur :{port} — {exc}") from exc
    return status(console_host)


def stop() -> Dict[str, Any]:
    global _server, _thread, _started_at, _last_error
    with _lock:
        server = _server
        _server = None
        _thread = None
        _started_at = 0.0
    if server is not None:
        try:
            server.shutdown()
            server.server_close()
        except Exception as exc:  # noqa: BLE001
            _last_error = str(exc)
    return status()
