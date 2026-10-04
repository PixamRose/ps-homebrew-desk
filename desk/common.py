"""Cross-platform helpers for PS Homebrew Desk (Mac / Windows / LAN / future iOS web)."""

from __future__ import annotations

import ipaddress
import json
import os
import platform
import socket
import subprocess
import sys
from pathlib import Path, PurePosixPath
from typing import Any, Dict, Optional

AUTHOR = "Pixam"


def configure_stdio() -> None:
    """Avoid UnicodeEncodeError on Windows cp1252 consoles / pythonw."""
    for stream in (sys.stdout, sys.stderr):
        try:
            reconf = getattr(stream, "reconfigure", None)
            if callable(reconf):
                reconf(encoding="utf-8", errors="replace")
        except Exception:
            pass


def remote_parent(path: str) -> str:
    """Parent of a console/FTP path (always POSIX, safe on Windows)."""
    cleaned = (path or "/").replace("\\", "/")
    parent = PurePosixPath(cleaned).parent.as_posix()
    if not parent or parent == ".":
        return "/"
    return parent if parent.startswith("/") else f"/{parent}"


def remote_name(path: str) -> str:
    """Basename of a console/FTP path (always POSIX)."""
    return PurePosixPath((path or "").replace("\\", "/")).name


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def project_root() -> Path:
    """Repository / install root (parent of the `desk` package in source mode)."""
    return Path(__file__).resolve().parents[1]


def bundle_root() -> Path:
    """Read-only resources (PyInstaller _MEIPASS, or project dir in source mode)."""
    if is_frozen() and hasattr(sys, "_MEIPASS"):
        return Path(getattr(sys, "_MEIPASS"))
    return project_root()


def app_root() -> Path:
    """Writable app directory — next to the .exe/.app when frozen."""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return project_root()


# Back-compat alias (source mode == project root)
ROOT = app_root()
VERSION_FILE = bundle_root() / "version.json"
UPDATES_DIR = app_root() / "updates"


def load_version() -> Dict[str, Any]:
    data = {
        "name": "PS Homebrew Desk",
        "version": "0.0.0",
        "channel": "dev",
        "notes": "",
        "author": AUTHOR,
    }
    try:
        raw = json.loads(VERSION_FILE.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            data.update(
                {
                    k: raw[k]
                    for k in ("name", "version", "channel", "notes", "author")
                    if k in raw
                }
            )
    except Exception:
        pass
    if not data.get("author"):
        data["author"] = AUTHOR
    return data


def app_version() -> str:
    return str(load_version().get("version") or "0.0.0")


def app_author() -> str:
    return str(load_version().get("author") or AUTHOR)


def host_platform() -> str:
    system = platform.system().lower()
    if system == "darwin":
        return "mac"
    if system == "windows":
        return "windows"
    if system.startswith("linux"):
        return "linux"
    return system or "unknown"


def lan_enabled() -> bool:
    return os.environ.get("DESK_LAN", "").strip().lower() in ("1", "true", "yes", "on")


def desk_bind_host() -> str:
    explicit = os.environ.get("DESK_HOST", "").strip()
    if explicit:
        return explicit
    return "0.0.0.0" if lan_enabled() else "127.0.0.1"


def desk_port() -> int:
    try:
        return int(os.environ.get("DESK_PORT", "8787"))
    except ValueError:
        return 8787


def desk_token() -> str:
    return os.environ.get("DESK_TOKEN", "").strip()


def is_loopback(ip: str) -> bool:
    try:
        return ipaddress.ip_address(ip).is_loopback
    except ValueError:
        return ip in ("127.0.0.1", "::1", "localhost")


def is_private_ip(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
        return bool(addr.is_private or addr.is_loopback)
    except ValueError:
        return False


def local_ip(prefer_host: str = "") -> str:
    """Best-effort LAN IPv4 (Mac / Windows / Linux)."""
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
    # UDP trick: no packets sent, just asks OS for egress interface
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(("8.8.8.8", 80))
        ip = sock.getsockname()[0]
        sock.close()
        if ip and not ip.startswith("127."):
            return ip
    except OSError:
        pass
    if sys.platform == "darwin":
        for iface in ("en0", "en1"):
            try:
                out = subprocess.check_output(["ipconfig", "getifaddr", iface], text=True).strip()
                if out:
                    return out
            except Exception:
                pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip and not ip.startswith("127."):
                return ip
    except Exception:
        pass
    return "127.0.0.1"


def lan_url(path: str = "/") -> str:
    ip = local_ip()
    port = desk_port()
    if not path.startswith("/"):
        path = "/" + path
    return f"http://{ip}:{port}{path}"


def desktop_notify(title: str, message: str) -> bool:
    """Best-effort native notification on Mac / Windows."""
    system = platform.system().lower()
    try:
        if system == "darwin":
            script = (
                f'display notification {json.dumps(message)} '
                f'with title {json.dumps(title)} '
                f'sound name "Glass"'
            )
            subprocess.run(["osascript", "-e", script], check=False, timeout=3)
            return True
        if system == "windows":
            # PowerShell toast (Windows 10+) — hide console window
            ps = (
                "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null; "
                "$template = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent("
                "[Windows.UI.Notifications.ToastTemplateType]::ToastText02); "
                "$text = $template.GetElementsByTagName('text'); "
                f"$text.Item(0).AppendChild($template.CreateTextNode({json.dumps(title)})) > $null; "
                f"$text.Item(1).AppendChild($template.CreateTextNode({json.dumps(message)})) > $null; "
                "$toast = [Windows.UI.Notifications.ToastNotification]::new($template); "
                "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('PS Homebrew Desk by Pixam').Show($toast);"
            )
            creationflags = 0
            if hasattr(subprocess, "CREATE_NO_WINDOW"):
                creationflags = subprocess.CREATE_NO_WINDOW
            subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-Command",
                    ps,
                ],
                check=False,
                timeout=6,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=creationflags,
            )
            return True
    except Exception:
        return False
    return False


def read_update_manifest() -> Optional[Dict[str, Any]]:
    path = UPDATES_DIR / "manifest.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def desk_runtime_info(prefer_host: str = "") -> Dict[str, Any]:
    ver = load_version()
    ip = local_ip(prefer_host)
    port = desk_port()
    manifest = read_update_manifest()
    extract = {}
    try:
        from desk.transfer import list_extract_tools

        extract = list_extract_tools()
    except Exception:
        extract = {}
    return {
        "ok": True,
        "name": ver.get("name"),
        "version": ver.get("version"),
        "channel": ver.get("channel"),
        "notes": ver.get("notes") or "",
        "author": ver.get("author") or AUTHOR,
        "platform": host_platform(),
        "python": sys.version.split()[0],
        "frozen": is_frozen(),
        "lan_enabled": lan_enabled(),
        "bind_host": desk_bind_host(),
        "port": port,
        "lan_ip": ip,
        "lan_url": f"http://{ip}:{port}/",
        "pwa_url": f"http://{ip}:{port}/",
        "token_required": bool(desk_token()),
        "update": manifest,
        "extract": extract,
        "iphone_hint": "Sur iPhone: Safari → partager → Sur l’écran d’accueil (PWA).",
        "windows_hint": "Windows: PSHomebrewDesk.exe (recommandé) ou start.bat + Python + WebView2.",
    }
