#!/usr/bin/env python3
"""Launch PS Homebrew Desk as a native window (macOS / Windows)."""

from __future__ import annotations

import json
import os
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

# Source mode: project on sys.path. Frozen (PyInstaller): bundled.
if not getattr(sys, "frozen", False):
    ROOT = Path(__file__).resolve().parent
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))

from desk_common import (  # noqa: E402
    app_author,
    app_root,
    app_version,
    configure_stdio,
    desk_bind_host,
    desk_port,
    host_platform,
    is_frozen,
    lan_enabled,
)

# UI always talks to local loopback even if the server also binds LAN.
UI_HOST = "127.0.0.1"
PORT = desk_port()


class DeskApi:
    """Native file/folder pickers for ultra-fast local→FTP transfers."""

    def pick_folder(self):
        import webview

        result = webview.windows[0].create_file_dialog(webview.FOLDER_DIALOG)
        if not result:
            return []
        if isinstance(result, (list, tuple)):
            return [str(p) for p in result]
        return [str(result)]

    def pick_files(self):
        import webview

        # Windows file dialog: keep descriptions free of '/' which breaks filters.
        result = webview.windows[0].create_file_dialog(
            webview.OPEN_DIALOG,
            allow_multiple=True,
            file_types=(
                "PKG ELF ZIP BIN (*.pkg;*.fpkg;*.elf;*.zip;*.bin)",
                "All files (*.*)",
            ),
        )
        if not result:
            return []
        return [str(p) for p in result]


def port_open(timeout: float = 0.3) -> bool:
    try:
        with socket.create_connection((UI_HOST, PORT), timeout=timeout):
            return True
    except OSError:
        return False


def wait_port(timeout: float = 10.0) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        if port_open(0.3):
            return True
        time.sleep(0.1)
    return False


def desk_health_ok() -> bool:
    """True if an existing Desk instance already answers on PORT."""
    try:
        with urllib.request.urlopen(f"http://{UI_HOST}:{PORT}/api/health", timeout=0.8) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
            return bool(data.get("ok"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError, ValueError):
        return False


def start_server() -> None:
    import app as desk

    try:
        desk.main()
    except SystemExit as exc:
        # Surface bind errors in a log next to the app (pythonw has no console).
        try:
            log = app_root() / "cache" / "desktop-server.log"
            log.parent.mkdir(parents=True, exist_ok=True)
            log.write_text(str(exc), encoding="utf-8")
        except Exception:
            pass


def webview_gui() -> Optional[str]:
    """Pick a native GUI backend for pywebview."""
    plat = host_platform()
    if plat == "mac":
        return "cocoa"
    if plat == "windows":
        # Edge Chromium WebView2 on modern Windows
        return "edgechromium"
    return None


def window_icon() -> Optional[str]:
    """Windows prefers .ico; Mac can use .icns / png."""
    root = app_root()
    bundle_candidates = [
        root / "assets" / "AppIcon.ico",
        root / "assets" / "AppIcon.icns",
        root / "assets" / "icon.png",
        root / "static" / "app-icon.png",
    ]
    if is_frozen() and hasattr(sys, "_MEIPASS"):
        meipass = Path(getattr(sys, "_MEIPASS"))
        bundle_candidates = [
            meipass / "assets" / "AppIcon.ico",
            meipass / "assets" / "AppIcon.icns",
            meipass / "assets" / "icon.png",
            meipass / "static" / "app-icon.png",
        ] + bundle_candidates
    for path in bundle_candidates:
        if path.is_file():
            return str(path)
    return None


def main() -> None:
    configure_stdio()
    # Keep desktop UX local; enable LAN with DESK_LAN=1 / start-lan.*
    os.environ.setdefault("DESK_HOST", desk_bind_host())
    # Ensure writable dirs exist next to the exe
    (app_root() / "payloads").mkdir(parents=True, exist_ok=True)
    (app_root() / "updates").mkdir(parents=True, exist_ok=True)
    (app_root() / "cache").mkdir(parents=True, exist_ok=True)

    # Second double-click: reuse the already running Desk server.
    reuse_existing = port_open() and desk_health_ok()
    if not reuse_existing:
        server = threading.Thread(target=start_server, daemon=True)
        server.start()
        if not wait_port():
            if desk_health_ok():
                reuse_existing = True
            else:
                raise SystemExit(
                    f"Desktop server failed to start on :{PORT}. "
                    "Ferme l'autre instance ou regarde cache/desktop-server.log"
                )

    try:
        import webview
    except ImportError as exc:
        raise SystemExit(
            "pywebview manquant. Installe avec:\n"
            "  python -m pip install --user -r requirements.txt\n"
            "Windows: installe aussi WebView2 Runtime (Edge).\n"
        ) from exc

    api = DeskApi()
    gui = webview_gui()
    author = app_author()
    title = f"PS Homebrew Desk v{app_version()} · by {author}"
    if lan_enabled():
        title += " · LAN"
    if reuse_existing:
        title += " · attach"

    window_kwargs = dict(
        title=title,
        url=f"http://{UI_HOST}:{PORT}/",
        js_api=api,
        width=1120,
        height=760,
        min_size=(860, 600),
        background_color="#E8EAED",
        confirm_close=False,
        easy_drag=False,
    )
    # pywebview versions differ: `icon` is not always accepted by create_window.
    icon = window_icon()
    if icon:
        try:
            import inspect

            if "icon" in inspect.signature(webview.create_window).parameters:
                window_kwargs["icon"] = icon
        except (TypeError, ValueError):
            pass

    window = webview.create_window(**window_kwargs)
    if icon and not window_kwargs.get("icon"):
        try:
            if hasattr(window, "set_icon"):
                window.set_icon(icon)
        except Exception:
            pass

    # Prefer explicit native backend; fall back to pywebview autodetection.
    if gui:
        try:
            webview.start(gui=gui)
            return
        except Exception:
            pass
    webview.start()


if __name__ == "__main__":
    main()
