#!/usr/bin/env python3
"""Launch PS Homebrew Desk as a native window (macOS / Windows)."""

from __future__ import annotations

import os
import socket
import sys
import threading
import time
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

        result = webview.windows[0].create_file_dialog(
            webview.OPEN_DIALOG,
            allow_multiple=True,
            file_types=(
                "PKG/FPKG/ELF (*.pkg;*.fpkg;*.elf;*.zip;*.bin)",
                "All files (*.*)",
            ),
        )
        if not result:
            return []
        return [str(p) for p in result]


def wait_port(timeout: float = 10.0) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        try:
            with socket.create_connection((UI_HOST, PORT), timeout=0.3):
                return True
        except OSError:
            time.sleep(0.1)
    return False


def start_server() -> None:
    import app as desk

    desk.main()


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
    # Keep desktop UX local; enable LAN with DESK_LAN=1 / start-lan.*
    os.environ.setdefault("DESK_HOST", desk_bind_host())
    # Ensure writable dirs exist next to the exe
    (app_root() / "payloads").mkdir(parents=True, exist_ok=True)
    (app_root() / "updates").mkdir(parents=True, exist_ok=True)
    (app_root() / "cache").mkdir(parents=True, exist_ok=True)

    server = threading.Thread(target=start_server, daemon=True)
    server.start()
    if not wait_port():
        raise SystemExit(f"Desktop server failed to start on :{PORT}")

    try:
        import webview
    except ImportError as exc:
        raise SystemExit(
            "pywebview manquant. Installe avec:\n"
            "  python -m pip install --user -r requirements.txt\n"
            "Windows: installe aussi « WebView2 Runtime » (Edge).\n"
        ) from exc

    api = DeskApi()
    gui = webview_gui()
    author = app_author()
    title = f"PS Homebrew Desk v{app_version()} · by {author}"
    if lan_enabled():
        title += " · LAN"

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
    icon = window_icon()
    if icon:
        window_kwargs["icon"] = icon

    webview.create_window(**window_kwargs)
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
