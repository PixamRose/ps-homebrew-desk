#!/usr/bin/env python3
"""PS Homebrew Desk — cross-platform companion (Mac / Windows / LAN / PWA) for PS5 homebrew over FTP."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import socket
import struct
import sys
import tempfile
import threading
import time
import urllib.request
import webbrowser
from datetime import datetime, timezone
from ftplib import FTP, error_perm
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlparse

from desk import transfer as xfer
from desk import relapse as relapse_host
from desk import games as games_mod
from desk import elfs as elfs_mod
from desk import companion as companion_mod
from desk import history as history_mod
from desk import discord_hook as discord_mod
from desk import eden as eden_mod
from desk import orbit as orbit_mod
from desk.common import (
    UPDATES_DIR,
    configure_stdio,
    remote_name,
    remote_parent,
    app_author,
    app_root,
    app_version,
    bundle_root,
    desk_bind_host,
    desk_port,
    desk_runtime_info,
    desk_token,
    desktop_notify,
    is_loopback,
    is_private_ip,
    lan_enabled,
    read_update_manifest,
)

ROOT = app_root()
BUNDLE = bundle_root()
STATIC = BUNDLE / "static"
CATALOG_DIR = BUNDLE / "catalog"
CATALOG = CATALOG_DIR / "default.json"
CATALOG_FILES = app_root() / "catalog" / "files"
DEFAULT_HOST = ""
FTP_PORT = 1337
ELFLDR_PORT = 9021
HOMEBREW_DIR = "/data/homebrew"
DATA_ROOT = "/data"
PAYLOADS_DIR = app_root() / "payloads"
# Writable: /data, /user (apps/saves installées), /mnt (USB…).
# Read-only: système et racines sensibles.
SAFE_WRITE_ROOTS = (DATA_ROOT, "/user", "/mnt", "/usb", "/homebrew")
BLOCKED_WRITE_EXACT = frozenset({"/", DATA_ROOT, "/homebrew"})
BLOCKED_WRITE_PREFIXES = (
    "/system",
    "/system_ex",
    "/priv",
    "/sdd_system",
    "/preinst",
    "/update",
    "/dev",
    "/host",
    "/app0",
    "/download0",
)
LOG_CANDIDATES = (
    "/data/etaHEN/etaHEN.log",
    "/data/etaHEN/etaHEN_util_daemon.log",
    "/data/OnionHEN/OnionHEN.log",
    "/data/shadowmount/debug.log",
    "/data/ps5_autoloader/autoload.txt",
)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def send_elf_to_loader(host: str, data: bytes, port: int = ELFLDR_PORT, timeout: float = 20.0) -> Dict[str, Any]:
    """Send a raw ELF payload to the console ELF loader (post-Relapse :9021)."""
    if not data:
        raise ValueError("ELF vide")
    if len(data) < 4 or data[:4] != b"\x7fELF":
        raise ValueError("Fichier invalide (pas un ELF)")
    with socket.create_connection((host, port), timeout=timeout) as sock:
        sock.settimeout(timeout)
        total = 0
        view = memoryview(data)
        while total < len(data):
            sent = sock.send(view[total:])
            if sent == 0:
                raise RuntimeError("Connexion elfldr interrompue pendant l’envoi")
            total += sent
        try:
            sock.shutdown(socket.SHUT_WR)
        except OSError:
            pass
    return {
        "host": host,
        "port": port,
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def list_local_payloads() -> List[Dict[str, Any]]:
    PAYLOADS_DIR.mkdir(parents=True, exist_ok=True)
    items: List[Dict[str, Any]] = []
    for path in sorted(PAYLOADS_DIR.glob("*.elf")):
        try:
            size = path.stat().st_size
        except OSError:
            continue
        items.append({"name": path.name, "path": str(path), "bytes": size})
    return items


def probe_port(host: str, port: int, timeout: float = 1.2) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def ftp_connect(host: str, port: int = FTP_PORT, timeout: float = 8.0) -> FTP:
    ftp = FTP()
    ftp.connect(host, port, timeout=timeout)
    ftp.login()
    ftp.set_pasv(True)
    return ftp


def ftp_list(ftp: FTP, path: str) -> List[Dict[str, Any]]:
    entries: List[Dict[str, Any]] = []
    try:
        ftp.cwd(path)
    except error_perm as exc:
        raise RuntimeError(f"Cannot open {path}: {exc}") from exc

    lines: List[str] = []
    ftp.retrlines("LIST", lines.append)
    for line in lines:
        parts = line.split(maxsplit=8)
        if len(parts) < 9:
            continue
        name = parts[8]
        if name in (".", ".."):
            continue
        entries.append(
            {
                "name": name,
                "type": "dir" if parts[0].startswith("d") else "file",
                "size": int(parts[4]) if parts[4].isdigit() else 0,
                "raw": line,
            }
        )
    return entries


def ftp_search(
    ftp: FTP,
    root: str,
    query: str,
    *,
    max_depth: int = 6,
    max_results: int = 200,
) -> List[Dict[str, Any]]:
    """Case-insensitive recursive name search under root."""
    query = (query or "").strip().lower()
    if not query:
        return []
    root = normalize_remote_path(root)
    results: List[Dict[str, Any]] = []

    def walk(path: str, depth: int) -> None:
        if len(results) >= max_results or depth > max_depth:
            return
        try:
            entries = ftp_list(ftp, path)
        except Exception:
            return
        for entry in entries:
            if len(results) >= max_results:
                return
            name = entry["name"]
            full = join_remote(path, name) if path != "/" else f"/{name}"
            if query in name.lower() or query in full.lower():
                results.append(
                    {
                        "name": name,
                        "type": entry["type"],
                        "size": entry.get("size") or 0,
                        "path": full,
                        "parent": path,
                    }
                )
            if entry["type"] == "dir":
                walk(full, depth + 1)

    walk(root, 0)
    return results


def ftp_read_text(ftp: FTP, path: str, limit: int = 256_000) -> str:
    chunks: List[bytes] = []
    total = 0

    def _cb(data: bytes) -> None:
        nonlocal total
        if total >= limit:
            return
        take = data[: max(0, limit - total)]
        chunks.append(take)
        total += len(take)

    ftp.retrbinary(f"RETR {path}", _cb)
    return b"".join(chunks).decode("utf-8", errors="replace")


def ftp_upload_bytes(ftp: FTP, remote_path: str, data: bytes) -> None:
    remote_path = assert_writable_path(remote_path)
    parent = remote_path.rsplit("/", 1)[0]
    ensure_remote_dir(ftp, parent)
    ftp.storbinary(f"STOR {remote_path}", BytesIO(data))


def ensure_remote_dir(ftp: FTP, path: str) -> None:
    if path in ("", "/"):
        return
    parts = [p for p in path.split("/") if p]
    cur = ""
    for part in parts:
        cur += "/" + part
        try:
            ftp.mkd(cur)
        except error_perm:
            pass


def normalize_remote_path(path: str) -> str:
    path = (path or "/").replace("\\", "/").strip() or "/"
    while "//" in path:
        path = path.replace("//", "/")
    if not path.startswith("/"):
        path = "/" + path
    parts = [p for p in path.split("/") if p and p != "."]
    if ".." in parts:
        raise ValueError("Chemin invalide")
    return "/" + "/".join(parts) if parts else "/"


def is_writable_path(path: str) -> bool:
    """Allow /data, /user, /mnt, /usb; block system roots."""
    path = normalize_remote_path(path)
    for blocked in BLOCKED_WRITE_PREFIXES:
        if path == blocked or path.startswith(blocked + "/"):
            return False
    for root in SAFE_WRITE_ROOTS:
        if path == root or path.startswith(root + "/"):
            return True
    return False


def assert_writable_path(path: str) -> str:
    path = normalize_remote_path(path)
    if not is_writable_path(path):
        raise PermissionError("Écriture bloquée sur les dossiers système")
    return path


def join_remote(parent: str, name: str) -> str:
    parent = normalize_remote_path(parent)
    name = remote_name(name)
    if not name or name in (".", ".."):
        raise ValueError("Nom invalide")
    return normalize_remote_path(f"{parent.rstrip('/')}/{name}")


def ftp_mkdir(ftp: FTP, path: str) -> None:
    path = assert_writable_path(path)
    parent = remote_parent(path)
    if parent and parent != ".":
        ensure_remote_dir(ftp, parent if parent.startswith("/") else "/" + parent)
    try:
        ftp.mkd(path)
    except error_perm as exc:
        raise RuntimeError(f"Impossible de créer {path}: {exc}") from exc


def ftp_rename(ftp: FTP, src: str, dst: str) -> None:
    src = assert_writable_path(src)
    dst = assert_writable_path(dst)
    if src == dst:
        return
    parent = remote_parent(dst)
    if not parent.startswith("/"):
        parent = "/" + parent
    ensure_remote_dir(ftp, parent)
    try:
        ftp.rename(src, dst)
    except error_perm as exc:
        raise RuntimeError(f"Impossible de déplacer/renommer: {exc}") from exc


def ftp_is_dir(ftp: FTP, path: str) -> bool:
    path = normalize_remote_path(path)
    try:
        ftp.cwd(path)
        return True
    except error_perm:
        return False


def ftp_copy_tree(ftp: FTP, src: str, dst: str) -> None:
    """Recursive copy of a directory within writable roots."""
    src = assert_writable_path(src)
    dst = assert_writable_path(dst)
    ensure_remote_dir(ftp, dst)
    for entry in ftp_list(ftp, src):
        child_src = join_remote(src, entry["name"])
        child_dst = join_remote(dst, entry["name"])
        if entry["type"] == "dir":
            ftp_copy_tree(ftp, child_src, child_dst)
        else:
            ftp_copy_file(ftp, child_src, child_dst)


def ftp_move(ftp: FTP, src: str, dst: str, is_dir: Optional[bool] = None) -> str:
    """Move via RNFR/RNTO when possible; fallback to copy+delete across volumes."""
    src = assert_writable_path(src)
    dst = assert_writable_path(dst)
    if src == dst:
        return "noop"
    if is_dir is None:
        is_dir = ftp_is_dir(ftp, src)
    # Fast path: same-volume rename
    try:
        ftp_rename(ftp, src, dst)
        return "rename"
    except RuntimeError:
        pass
    # Fallback: copy then delete (needed across /data ↔ /user, etc.)
    if is_dir:
        ftp_copy_tree(ftp, src, dst)
        ftp_delete(ftp, src, is_dir=True)
    else:
        ftp_copy_file(ftp, src, dst)
        ftp_delete(ftp, src, is_dir=False)
    return "copy_delete"


def ftp_delete(ftp: FTP, path: str, is_dir: bool = False) -> None:
    path = assert_writable_path(path)
    if path.rstrip("/") in BLOCKED_WRITE_EXACT or path.rstrip("/") in SAFE_WRITE_ROOTS:
        raise PermissionError("Impossible de supprimer cette racine protégée")
    try:
        if is_dir:
            _ftp_rmtree(ftp, path)
        else:
            ftp.delete(path)
    except error_perm as exc:
        raise RuntimeError(f"Impossible de supprimer {path}: {exc}") from exc


def _ftp_rmtree(ftp: FTP, path: str) -> None:
    path = assert_writable_path(path)
    try:
        entries = ftp_list(ftp, path)
    except Exception:
        entries = []
    for entry in entries:
        child = join_remote(path, entry["name"])
        if entry["type"] == "dir":
            _ftp_rmtree(ftp, child)
        else:
            ftp.delete(child)
    ftp.rmd(path)


def ftp_copy_file(ftp: FTP, src: str, dst: str) -> None:
    """Copy a single file within /data via RETR+STOR."""
    src = assert_writable_path(src)
    dst = assert_writable_path(dst)
    buf = BytesIO()
    ftp.retrbinary(f"RETR {src}", buf.write)
    buf.seek(0)
    parent = remote_parent(dst)
    if not parent.startswith("/"):
        parent = "/" + parent
    ensure_remote_dir(ftp, parent)
    ftp.storbinary(f"STOR {dst}", buf)


def mac_notify(title: str, message: str) -> bool:
    """Backward-compatible name — notifies on Mac and Windows."""
    return desktop_notify(title, message)


def try_legacy_cmd_notify(host: str, message: str) -> bool:
    """If etaHEN legacy TCP cmd server (:9028) is up, unknown cmds toast on console."""
    if not probe_port(host, 9028, timeout=0.6):
        return False
    # struct Command layout used by util legacy server (magic, cmd, pid, msg1...)
    # Sending an unknown cmd triggers notify("... Got Command %i").
    try:
        payload = bytearray(0x400)
        struct.pack_into("<I", payload, 0, 0xDEADBEEF)
        struct.pack_into("<I", payload, 4, 0x50534844)  # 'PSHD'
        msg = message.encode("utf-8")[:200]
        payload[16 : 16 + len(msg)] = msg
        with socket.create_connection((host, 9028), timeout=2.0) as sock:
            sock.sendall(payload)
            sock.settimeout(1.0)
            try:
                sock.recv(64)
            except OSError:
                pass
        return True
    except OSError:
        return False


def try_control_ping(host: str, message: str) -> bool:
    """Best-effort ping on OnionHEN/etaHEN control port 9048."""
    if not probe_port(host, 9048, timeout=0.6):
        return False
    try:
        body = message.encode("utf-8")[:240]
        frames = [
            b"NOTIFY " + body + b"\n",
            struct.pack("<II", 0x4E544659, len(body)) + body,  # NTFY
            struct.pack("<II", 0x48454E4F, 1) + body + b"\x00",  # ONEH
        ]
        for frame in frames:
            with socket.create_connection((host, 9048), timeout=2.0) as sock:
                sock.sendall(frame)
                sock.settimeout(0.8)
                try:
                    sock.recv(16)
                except OSError:
                    pass
        return True
    except OSError:
        return False


def console_notify(host: str, message: str = "PS Homebrew Desk\nConnexion etablie") -> Dict[str, Any]:
    """Safe console ping: FTP beacon + optional toast channels. Never touches /system."""
    result = {
        "message": message,
        "ftp_beacon": False,
        "legacy_cmd_toast": False,
        "control_ping": False,
        "mac_notification": False,
        "remote": f"{HOMEBREW_DIR}/PSHD_CONNECTED.txt",
    }
    beacon = (
        f"{message}\n"
        f"host={host}\n"
        f"time={now_iso()}\n"
        f"source=PS Homebrew Desk\n"
    ).encode("utf-8")
    try:
        with ftp_connect(host) as ftp:
            ftp_upload_bytes(ftp, result["remote"], beacon)
            result["ftp_beacon"] = True
    except Exception as exc:  # noqa: BLE001
        result["ftp_error"] = str(exc)

    result["legacy_cmd_toast"] = try_legacy_cmd_notify(host, message)
    result["control_ping"] = try_control_ping(host, message)
    result["mac_notification"] = mac_notify("PS Homebrew Desk", message.replace("\n", " — "))
    result["console_toast_likely"] = bool(result["legacy_cmd_toast"])
    return result


def load_catalog() -> Dict[str, Any]:
    if not CATALOG.exists():
        return {"items": []}
    return json.loads(CATALOG.read_text(encoding="utf-8"))


def doctor(host: str, ping: bool = False) -> Dict[str, Any]:
    ports = {
        "ftp_1337": probe_port(host, 1337),
        "elfldr_9021": probe_port(host, 9021),
        "http_9120": probe_port(host, 9120),
        "control_9048": probe_port(host, 9048),
    }
    result: Dict[str, Any] = {
        "host": host,
        "checked_at": now_iso(),
        "ports": ports,
        "ftp_ok": False,
        "homebrew": [],
        "autoload": None,
        "warnings": [],
        "hen_hints": [],
    }

    if not ports["ftp_1337"]:
        result["warnings"].append("FTP 1337 unreachable — is HEN/utils running?")
        return result

    try:
        with ftp_connect(host) as ftp:
            result["ftp_ok"] = True
            try:
                result["homebrew"] = ftp_list(ftp, HOMEBREW_DIR)
            except Exception as exc:  # noqa: BLE001
                result["warnings"].append(f"/data/homebrew: {exc}")
            try:
                autoload = ftp_read_text(ftp, "/data/ps5_autoloader/autoload.txt", limit=8_000)
                result["autoload"] = autoload
                lower = autoload.lower()
                has_onion = "onionhen" in lower
                has_etahen = "etahen" in lower
                if has_onion and has_etahen:
                    result["warnings"].append("Autoload lists OnionHEN and etaHEN — double HEN risk")
                if has_onion:
                    result["hen_hints"].append("OnionHEN in autoload")
                if has_etahen:
                    result["hen_hints"].append("etaHEN in autoload")
            except Exception:
                result["autoload"] = None

            for marker, label in (
                ("/data/etaHEN/etaHEN.log", "etaHEN log present"),
                ("/data/OnionHEN/OnionHEN.log", "OnionHEN log present"),
                ("/system_tmp/shadowmount.sock", "ShadowMount socket present"),
            ):
                try:
                    ftp.size(marker)
                    result["hen_hints"].append(label)
                except Exception:
                    pass
    except Exception as exc:  # noqa: BLE001
        result["warnings"].append(f"FTP error: {exc}")

    if ports["ftp_1337"] and not ports["elfldr_9021"]:
        result["warnings"].append("ELF loader :9021 closed — payload send may fail")

    if ping and result["ftp_ok"]:
        result["notify"] = console_notify(host)
        # Refresh listing so the beacon file appears immediately in the UI.
        try:
            with ftp_connect(host) as ftp:
                result["homebrew"] = ftp_list(ftp, HOMEBREW_DIR)
        except Exception:
            pass

    return result


class DeskHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, directory=str(STATIC), **kwargs)

    def log_message(self, fmt: str, *args: Any) -> None:
        print(f"[desk] {self.address_string()} {fmt % args}")

    def _json(self, payload: Any, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _error(self, message: str, status: int = 400) -> None:
        self._json({"ok": False, "error": message}, status=status)

    def _read_json(self) -> Dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        if not raw:
            return {}
        return json.loads(raw.decode("utf-8"))

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)
        host = (qs.get("host") or [DEFAULT_HOST])[0].strip() or DEFAULT_HOST

        if path == "/api/health":
            return self._json(
                {
                    "ok": True,
                    "service": "PS Homebrew Desk",
                    "version": app_version(),
                    "lan_enabled": lan_enabled(),
                    "time": now_iso(),
                }
            )

        if path == "/api/desk/info":
            return self._json(desk_runtime_info(host))

        if path == "/api/games":
            return self._handle_games_list(host)

        if path == "/api/games/info":
            return self._handle_games_info(host, qs)

        if path == "/api/games/icon":
            return self._handle_games_icon(host, qs)

        if path == "/api/elfs":
            return self._handle_elfs_list(host)

        if path == "/api/elfs/info":
            return self._handle_elfs_info(host, qs)

        if path == "/api/eden/status":
            return self._handle_eden_status(host)

        if path == "/api/eden/release":
            return self._handle_eden_release()

        if path == "/api/orbit/status":
            return self._handle_orbit_status(host)

        if path == "/api/orbit/release":
            return self._handle_orbit_release()

        if path == "/api/desk/update/manifest":
            manifest = read_update_manifest()
            if not manifest:
                return self._json({"ok": True, "available": False, "manifest": None})
            return self._json({"ok": True, "available": True, "manifest": manifest})

        if path.startswith("/updates/"):
            return self._serve_updates(path)

        if path == "/api/doctor":
            ping = (qs.get("ping") or ["0"])[0] in ("1", "true", "yes")
            return self._json({"ok": True, "doctor": doctor(host, ping=ping)})

        if path == "/api/notify":
            message = (qs.get("message") or ["PS Homebrew Desk\nConnexion etablie"])[0]
            try:
                return self._json({"ok": True, "notify": console_notify(host, message)})
            except Exception as exc:  # noqa: BLE001
                return self._error(str(exc), status=502)

        if path == "/api/homebrew":
            try:
                with ftp_connect(host) as ftp:
                    items = ftp_list(ftp, HOMEBREW_DIR)
                return self._json({"ok": True, "path": HOMEBREW_DIR, "items": items})
            except Exception as exc:  # noqa: BLE001
                return self._error(str(exc), status=502)

        if path == "/api/logs":
            name = (qs.get("name") or ["etahen"])[0].lower()
            mapping = {
                "etahen": "/data/etaHEN/etaHEN.log",
                "util": "/data/etaHEN/etaHEN_util_daemon.log",
                "onionhen": "/data/OnionHEN/OnionHEN.log",
                "shadowmount": "/data/shadowmount/debug.log",
                "autoload": "/data/ps5_autoloader/autoload.txt",
            }
            remote = mapping.get(name)
            if not remote:
                return self._error("Unknown log name")
            try:
                with ftp_connect(host) as ftp:
                    text = ftp_read_text(ftp, remote, limit=200_000)
                return self._json({"ok": True, "path": remote, "content": text})
            except Exception as exc:  # noqa: BLE001
                return self._error(str(exc), status=502)

        if path == "/api/catalog":
            return self._json({"ok": True, "catalog": load_catalog()})

        if path.startswith("/catalog/files/"):
            return self._serve_catalog_file(path)

        if path == "/api/transfer/job":
            job_id = (qs.get("id") or [""])[0]
            job = xfer.get_job(job_id)
            if not job:
                return self._error("Job introuvable", status=404)
            return self._json({"ok": True, "job": job.snapshot()})

        if path == "/api/transfer/jobs":
            try:
                limit = int((qs.get("limit") or ["40"])[0])
            except ValueError:
                limit = 40
            return self._json({"ok": True, "jobs": xfer.list_jobs(limit=limit)})

        if path == "/api/transfer/history":
            try:
                limit = int((qs.get("limit") or ["40"])[0])
            except ValueError:
                limit = 40
            return self._json({"ok": True, "history": history_mod.list_history(limit=limit)})

        if path == "/api/profiles":
            return self._json({"ok": True, **history_mod.get_profiles_bundle()})

        if path == "/api/prefs":
            return self._json({"ok": True, "prefs": history_mod.get_prefs()})

        if path == "/api/links":
            return self._json({"ok": True, "links": history_mod.get_community_links()})

        if path == "/api/discord":
            wh = discord_mod.get_webhook()
            return self._json({"ok": True, "configured": bool(wh), "url": wh[:48] + ("…" if len(wh) > 48 else "")})

        if path == "/api/companion":
            return self._json(companion_mod.status_payload())

        if path == "/api/fs/list":
            return self._handle_fs_list(host, qs)

        if path == "/api/fs/search":
            return self._handle_fs_search(host, qs)

        if path == "/api/fs/writable":
            try:
                remote = normalize_remote_path((qs.get("path") or [HOMEBREW_DIR])[0])
            except ValueError as exc:
                return self._error(str(exc))
            return self._json({"ok": True, "path": remote, "writable": is_writable_path(remote)})

        if path == "/api/relapse/status":
            doctor_state = doctor(host, ping=False)
            ports = doctor_state.get("ports") or {}
            payload = relapse_host.status(host)
            payload["console"] = {
                "host": host,
                "detected": bool(doctor_state.get("ftp_ok") or ports.get("elfldr_9021")),
                "ftp_ok": bool(doctor_state.get("ftp_ok")),
                "elfldr_ok": bool(ports.get("elfldr_9021")),
                "ports": ports,
                "warnings": doctor_state.get("warnings") or [],
            }
            payload["payloads"] = list_local_payloads()
            return self._json({"ok": True, "relapse": payload})

        if path == "/api/elfldr/payloads":
            return self._json({"ok": True, "payloads": list_local_payloads(), "directory": str(PAYLOADS_DIR)})

        if path == "/" or path.startswith("/static/") or Path(path.lstrip("/")).suffix:
            if path == "/":
                self.path = "/index.html"
            return SimpleHTTPRequestHandler.do_GET(self)

        return self._error("Not found", status=404)

    def _is_local_client(self) -> bool:
        """Trusted client: loopback always; private LAN when DESK_LAN=1 (+ optional token)."""
        ip = self.client_address[0]
        if is_loopback(ip) or ip in ("localhost",):
            return True
        if not lan_enabled():
            return False
        if not is_private_ip(ip):
            return False
        token = desk_token()
        if not token:
            return True
        provided = (self.headers.get("X-PSHD-Token") or "").strip()
        if provided == token:
            return True
        # Also allow ?token= for simple Safari / PWA fetches
        qs = parse_qs(urlparse(self.path).query)
        return (qs.get("token") or [""])[0] == token

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/api/upload":
            return self._handle_upload()

        if path == "/api/install":
            return self._handle_install()

        if path == "/api/transfer/local":
            return self._handle_transfer_local()

        if path == "/api/transfer/raw":
            return self._handle_transfer_raw()

        if path == "/api/fetch-upload":
            return self._handle_fetch_upload()

        if path == "/api/transfer/cancel":
            return self._handle_transfer_cancel()

        if path == "/api/transfer/pause":
            return self._handle_transfer_pause()

        if path == "/api/transfer/resume":
            return self._handle_transfer_resume()

        if path == "/api/transfer/retry":
            return self._handle_transfer_retry()

        if path == "/api/transfer/history/clear":
            if not self._is_local_client():
                return self._error("Réservé au réseau de confiance", status=403)
            history_mod.clear_history()
            return self._json({"ok": True})

        if path == "/api/profiles":
            return self._handle_profiles_save()

        if path == "/api/prefs":
            return self._handle_prefs_save()

        if path == "/api/links":
            return self._handle_links_save()

        if path == "/api/discord":
            return self._handle_discord_save()

        if path == "/api/companion":
            return self._handle_companion_config()

        if path == "/api/relapse/setup":
            return self._handle_relapse_setup()

        if path == "/api/relapse/start":
            return self._handle_relapse_start()

        if path == "/api/relapse/stop":
            return self._handle_relapse_stop()

        if path == "/api/elfldr/send":
            return self._handle_elfldr_send()

        if path == "/api/desk/publish-update":
            return self._handle_publish_update()

        if path == "/api/games/uninstall":
            return self._handle_games_uninstall()

        if path == "/api/elfs/uninstall":
            return self._handle_elfs_uninstall()

        if path == "/api/elfs/update":
            return self._handle_elfs_update()

        if path == "/api/eden/install":
            return self._handle_eden_install()

        if path == "/api/eden/push":
            return self._handle_eden_push()

        if path == "/api/eden/delete-rom":
            return self._handle_eden_delete_rom()

        if path == "/api/orbit/install":
            return self._handle_orbit_install()

        if path == "/api/orbit/elfldr":
            return self._handle_orbit_elfldr()

        if path == "/api/open-external":
            return self._handle_open_external()

        if path == "/api/fs/mkdir":
            return self._handle_fs_mkdir()

        if path == "/api/fs/rename":
            return self._handle_fs_rename()

        if path == "/api/fs/move":
            return self._handle_fs_move()

        if path == "/api/fs/copy":
            return self._handle_fs_copy()

        if path == "/api/fs/delete":
            return self._handle_fs_delete()

        return self._error("Not found", status=404)

    def _handle_elfldr_send(self) -> None:
        if not self._is_local_client():
            return self._error("Envoi ELF réservé à localhost", status=403)
        try:
            body = self._read_json()
        except Exception:
            return self._error("JSON invalide")
        host = (body.get("host") or DEFAULT_HOST).strip()
        port = int(body.get("port") or ELFLDR_PORT)
        if not probe_port(host, port):
            return self._error(f"elfldr :{port} fermé — lance Relapse d’abord", status=409)

        data: Optional[bytes] = None
        source = ""
        local_path = (body.get("path") or "").strip()
        remote_path = (body.get("remote_path") or "").strip()
        filename = (body.get("filename") or "").strip()
        b64 = body.get("data_base64") or ""

        if remote_path:
            try:
                remote_path = normalize_remote_path(remote_path)
            except ValueError as exc:
                return self._error(str(exc))
            if not remote_path.lower().endswith(".elf"):
                return self._error("remote_path doit être un .elf")
            try:
                buf = BytesIO()
                with ftp_connect(host) as ftp:
                    ftp.retrbinary(f"RETR {remote_path}", buf.write)
                data = buf.getvalue()
                source = remote_path
                filename = filename or remote_name(remote_path)
            except Exception as exc:  # noqa: BLE001
                return self._error(f"FTP RETR échoué: {exc}", status=502)
        elif local_path:
            path = Path(local_path).expanduser().resolve()
            allowed_roots = [PAYLOADS_DIR.resolve(), (ROOT / "vendor").resolve()]
            if not any(str(path).startswith(str(root) + os.sep) or path == root for root in allowed_roots):
                # allow absolute paths picked via native dialog only under user Downloads/Desktop/homebrew desk
                home = Path.home().resolve()
                extra = [home / "Downloads", home / "Desktop", ROOT.resolve()]
                if not any(str(path).startswith(str(root) + os.sep) or path == root for root in extra):
                    return self._error("Chemin ELF non autorisé", status=403)
            if not path.is_file():
                return self._error("Fichier introuvable")
            data = path.read_bytes()
            source = str(path)
            filename = filename or path.name
        elif filename and not b64:
            path = (PAYLOADS_DIR / Path(filename).name).resolve()
            if not str(path).startswith(str(PAYLOADS_DIR.resolve()) + os.sep):
                return self._error("Nom de payload invalide", status=400)
            if not path.is_file():
                return self._error(f"Place {path.name} dans {PAYLOADS_DIR}")
            data = path.read_bytes()
            source = str(path)
        elif b64:
            try:
                data = base64.b64decode(b64)
            except Exception:
                return self._error("Base64 invalide")
            source = filename or "upload.elf"
        else:
            return self._error("Fournis path, remote_path, filename (dossier payloads/) ou data_base64")

        try:
            result = send_elf_to_loader(host, data, port=port)
            result["filename"] = filename or Path(source).name
            result["source"] = source
            # brief wait then report FTP if HEN came up
            ftp_up = probe_port(host, FTP_PORT, timeout=2.0)
            result["ftp_ok"] = ftp_up
            result["note"] = (
                "FTP :1337 ouvert — HEN probablement up"
                if ftp_up
                else "ELF envoyé. Si c’était etaHEN, attends 10–20s puis Connecter (FTP 1337)."
            )
            return self._json({"ok": True, "send": result})
        except Exception as exc:  # noqa: BLE001
            return self._error(str(exc), status=502)

    def _handle_relapse_setup(self) -> None:
        if not self._is_local_client():
            return self._error("Setup Relapse réservé à localhost", status=403)
        try:
            body = self._read_json()
        except Exception:
            body = {}
        host = (body.get("host") or DEFAULT_HOST).strip()
        try:
            path = relapse_host.ensure_relapse()
            return self._json({"ok": True, "directory": str(path), "relapse": relapse_host.status(host)})
        except Exception as exc:  # noqa: BLE001
            return self._error(str(exc), status=502)

    def _handle_relapse_start(self) -> None:
        if not self._is_local_client():
            return self._error("Start Relapse réservé à localhost", status=403)
        try:
            body = self._read_json()
        except Exception:
            body = {}
        host = (body.get("host") or DEFAULT_HOST).strip()
        port = int(body.get("port") or relapse_host.DEFAULT_PORT)
        # Relapse is a pre-HEN browser stage: do not require FTP/HEN.
        # Optional gate only if the client explicitly asks for it.
        require_console = bool(body.get("require_console", False))
        doctor_state = doctor(host, ping=False)
        if require_console and not doctor_state.get("ftp_ok"):
            return self._error("Console non détectée (FTP 1337). Connecte la PS5 d’abord.", status=409)
        try:
            payload = relapse_host.start(console_host=host, port=port)
            payload["console"] = {
                "host": host,
                "detected": bool(doctor_state.get("ftp_ok")),
                "ports": doctor_state.get("ports") or {},
                "warnings": doctor_state.get("warnings") or [],
            }
            return self._json({"ok": True, "relapse": payload})
        except Exception as exc:  # noqa: BLE001
            return self._error(str(exc), status=502)

    def _handle_relapse_stop(self) -> None:
        if not self._is_local_client():
            return self._error("Stop Relapse réservé à localhost", status=403)
        try:
            return self._json({"ok": True, "relapse": relapse_host.stop()})
        except Exception as exc:  # noqa: BLE001
            return self._error(str(exc), status=502)

    def _normalize_fs_path(self, path: str) -> str:
        return normalize_remote_path(path)

    def _handle_fs_list(self, host: str, qs: Dict[str, List[str]]) -> None:
        try:
            remote = self._normalize_fs_path((qs.get("path") or ["/data/homebrew"])[0])
        except ValueError as exc:
            return self._error(str(exc))
        try:
            with ftp_connect(host) as ftp:
                items = ftp_list(ftp, remote)
            items.sort(key=lambda it: (0 if it["type"] == "dir" else 1, it["name"].lower()))
            parent = remote_parent(remote) if remote != "/" else "/"
            if parent != "/" and not parent.startswith("/"):
                parent = "/" + parent
            return self._json(
                {
                    "ok": True,
                    "path": remote,
                    "parent": parent if remote != "/" else "/",
                    "writable": is_writable_path(remote),
                    "items": items,
                }
            )
        except Exception as exc:  # noqa: BLE001
            return self._error(str(exc), status=502)

    def _handle_fs_search(self, host: str, qs: Dict[str, List[str]]) -> None:
        query = (qs.get("q") or [""])[0].strip()
        if len(query) < 2:
            return self._error("Tape au moins 2 caractères")
        try:
            remote = self._normalize_fs_path((qs.get("path") or [DATA_ROOT])[0])
        except ValueError as exc:
            return self._error(str(exc))
        try:
            depth = int((qs.get("depth") or ["6"])[0])
        except ValueError:
            depth = 6
        depth = max(1, min(depth, 10))
        try:
            limit = int((qs.get("limit") or ["200"])[0])
        except ValueError:
            limit = 200
        limit = max(1, min(limit, 500))
        try:
            with ftp_connect(host) as ftp:
                items = ftp_search(ftp, remote, query, max_depth=depth, max_results=limit)
            return self._json(
                {
                    "ok": True,
                    "path": remote,
                    "query": query,
                    "truncated": len(items) >= limit,
                    "count": len(items),
                    "writable": is_writable_path(remote),
                    "items": items,
                }
            )
        except Exception as exc:  # noqa: BLE001
            return self._error(str(exc), status=502)

    def _fs_body(self) -> Dict[str, Any]:
        try:
            return self._read_json()
        except Exception:
            return {}

    def _handle_fs_mkdir(self) -> None:
        if not self._is_local_client():
            return self._error("mkdir réservé à localhost", status=403)
        body = self._fs_body()
        host = (body.get("host") or DEFAULT_HOST).strip()
        parent = body.get("path") or HOMEBREW_DIR
        name = (body.get("name") or "").strip()
        try:
            remote = join_remote(parent, name)
            with ftp_connect(host) as ftp:
                ftp_mkdir(ftp, remote)
            return self._json({"ok": True, "path": remote})
        except Exception as exc:  # noqa: BLE001
            return self._error(str(exc), status=502)

    def _handle_fs_rename(self) -> None:
        if not self._is_local_client():
            return self._error("rename réservé à localhost", status=403)
        body = self._fs_body()
        host = (body.get("host") or DEFAULT_HOST).strip()
        src = body.get("src") or ""
        new_name = (body.get("name") or "").strip()
        try:
            src_path = normalize_remote_path(src)
            dst = join_remote(remote_parent(src_path), new_name)
            with ftp_connect(host) as ftp:
                ftp_rename(ftp, src_path, dst)
            return self._json({"ok": True, "src": src_path, "dst": dst})
        except Exception as exc:  # noqa: BLE001
            return self._error(str(exc), status=502)

    def _unique_dst_name(self, ftp: FTP, dst_dir: str, name: str) -> str:
        dst_dir = normalize_remote_path(dst_dir)
        try:
            existing = {e["name"] for e in ftp_list(ftp, dst_dir)}
        except Exception:
            existing = set()
        if name not in existing:
            return join_remote(dst_dir, name)
        stem = Path(name).stem
        suf = Path(name).suffix
        # directories often have no suffix; still fine
        n = 1
        while f"{stem}-copy{n}{suf}" in existing:
            n += 1
        return join_remote(dst_dir, f"{stem}-copy{n}{suf}")

    def _handle_fs_move(self) -> None:
        if not self._is_local_client():
            return self._error("move réservé à localhost", status=403)
        body = self._fs_body()
        host = (body.get("host") or DEFAULT_HOST).strip()
        src = body.get("src") or ""
        dst_dir = body.get("dst_dir") or ""
        is_dir = body.get("is_dir")
        try:
            src_path = normalize_remote_path(src)
            name = Path(src_path).name
            with ftp_connect(host) as ftp:
                if is_dir is None:
                    is_dir = ftp_is_dir(ftp, src_path)
                else:
                    is_dir = bool(is_dir)
                dst = join_remote(dst_dir, name)
                # avoid clobber: if exists, rename with suffix for move target
                try:
                    existing = {e["name"] for e in ftp_list(ftp, normalize_remote_path(dst_dir))}
                except Exception:
                    existing = set()
                if name in existing:
                    dst = self._unique_dst_name(ftp, dst_dir, name)
                mode = ftp_move(ftp, src_path, dst, is_dir=bool(is_dir))
            return self._json({"ok": True, "src": src_path, "dst": dst, "mode": mode})
        except Exception as exc:  # noqa: BLE001
            return self._error(str(exc), status=502)

    def _handle_fs_copy(self) -> None:
        if not self._is_local_client():
            return self._error("copy réservé à localhost", status=403)
        body = self._fs_body()
        host = (body.get("host") or DEFAULT_HOST).strip()
        src = body.get("src") or ""
        dst_dir = body.get("dst_dir") or ""
        is_dir = body.get("is_dir")
        try:
            src_path = normalize_remote_path(src)
            with ftp_connect(host) as ftp:
                if is_dir is None:
                    is_dir = ftp_is_dir(ftp, src_path)
                else:
                    is_dir = bool(is_dir)
                name = Path(src_path).name
                dst = self._unique_dst_name(ftp, dst_dir, name)
                if is_dir:
                    ftp_copy_tree(ftp, src_path, dst)
                else:
                    ftp_copy_file(ftp, src_path, dst)
            return self._json({"ok": True, "src": src_path, "dst": dst, "is_dir": bool(is_dir)})
        except Exception as exc:  # noqa: BLE001
            return self._error(str(exc), status=502)

    def _handle_fs_delete(self) -> None:
        if not self._is_local_client():
            return self._error("delete réservé à localhost", status=403)
        body = self._fs_body()
        host = (body.get("host") or DEFAULT_HOST).strip()
        path = body.get("path") or ""
        is_dir = bool(body.get("is_dir"))
        try:
            remote = normalize_remote_path(path)
            with ftp_connect(host) as ftp:
                ftp_delete(ftp, remote, is_dir=is_dir)
            return self._json({"ok": True, "path": remote})
        except Exception as exc:  # noqa: BLE001
            return self._error(str(exc), status=502)

    def _handle_fetch_upload(self) -> None:
        if not self._is_local_client():
            return self._error("Lien / fetch réservé au réseau de confiance", status=403)
        try:
            body = self._read_json()
        except Exception:
            return self._error("Invalid JSON")
        host = (body.get("host") or DEFAULT_HOST).strip()
        url = (body.get("url") or "").strip()
        filename = (body.get("filename") or "").strip()
        dest_root = (body.get("dest_root") or HOMEBREW_DIR).strip()
        password = str(body.get("password") or body.get("archive_password") or "")
        extract_raw = body.get("extract", True)
        extract = bool(extract_raw) if not isinstance(extract_raw, str) else extract_raw.lower() not in (
            "0",
            "false",
            "no",
        )
        if not url:
            return self._error("Missing url")
        try:
            dest_root = assert_writable_path(dest_root)
        except (ValueError, PermissionError) as exc:
            return self._error(str(exc))
        try:
            job = xfer.start_url_transfer(
                host,
                url,
                filename=filename,
                dest_root=dest_root,
                password=password,
                extract=extract,
            )
            return self._json({"ok": True, "job": job.snapshot(), "dest_root": dest_root})
        except Exception as exc:  # noqa: BLE001
            return self._error(str(exc), status=502)

    def _handle_transfer_cancel(self) -> None:
        if not self._is_local_client():
            return self._error("Annulation réservée au réseau de confiance", status=403)
        try:
            body = self._read_json()
        except Exception:
            return self._error("Invalid JSON")
        job_id = str(body.get("id") or "").strip()
        if not job_id:
            return self._error("Missing job id")
        job = xfer.cancel_job(job_id)
        if not job:
            return self._error("Job introuvable", status=404)
        try:
            companion_mod.notify_job_obj(job, force=True)
        except Exception:
            pass
        return self._json({"ok": True, "job": job.snapshot(), "cancel_requested": True})

    def _handle_transfer_pause(self) -> None:
        if not self._is_local_client():
            return self._error("Pause réservée au réseau de confiance", status=403)
        try:
            body = self._read_json()
        except Exception:
            return self._error("Invalid JSON")
        job = xfer.pause_job(str(body.get("id") or "").strip())
        if not job:
            return self._error("Job introuvable", status=404)
        return self._json({"ok": True, "job": job.snapshot()})

    def _handle_transfer_resume(self) -> None:
        if not self._is_local_client():
            return self._error("Reprise réservée au réseau de confiance", status=403)
        try:
            body = self._read_json()
        except Exception:
            return self._error("Invalid JSON")
        job = xfer.resume_job(str(body.get("id") or "").strip())
        if not job:
            return self._error("Job introuvable", status=404)
        return self._json({"ok": True, "job": job.snapshot()})

    def _handle_transfer_retry(self) -> None:
        if not self._is_local_client():
            return self._error("Retry réservé au réseau de confiance", status=403)
        try:
            body = self._read_json()
        except Exception:
            return self._error("Invalid JSON")
        # Prefer explicit payload; else look up history / live job
        host = (body.get("host") or DEFAULT_HOST or "").strip()
        paths = body.get("paths") or []
        dest_root = (body.get("dest_root") or HOMEBREW_DIR).strip()
        url = (body.get("url") or "").strip()
        job_id = str(body.get("id") or "").strip()
        if job_id and (not paths and not url):
            live = xfer.get_job(job_id)
            snap = live.snapshot() if live else None
            if not snap:
                for row in history_mod.list_history(80):
                    if row.get("id") == job_id:
                        snap = row
                        break
            if snap:
                host = host or str(snap.get("host") or "")
                paths = snap.get("source_paths") or []
                dest_root = str(snap.get("dest_root") or dest_root)
                url = str(snap.get("source_url") or "")
        try:
            if url:
                job = xfer.start_url_transfer(host, url, dest_root=dest_root)
            else:
                if not isinstance(paths, list) or not paths:
                    return self._error("Rien à relancer (pas de chemins / URL)")
                job = xfer.start_transfer(host, [str(p) for p in paths], dest_root=dest_root)
            return self._json({"ok": True, "job": job.snapshot()})
        except Exception as exc:  # noqa: BLE001
            return self._error(str(exc), status=502)

    def _handle_profiles_save(self) -> None:
        if not self._is_local_client():
            return self._error("Profils réservés au réseau de confiance", status=403)
        try:
            body = self._read_json()
        except Exception:
            return self._error("Invalid JSON")
        profiles = body.get("profiles") if isinstance(body.get("profiles"), list) else []
        active = str(body.get("active") or "")
        saved = history_mod.save_profiles(profiles, active=active)
        return self._json({"ok": True, **saved})

    def _handle_prefs_save(self) -> None:
        if not self._is_local_client():
            return self._error("Réglages réservés au réseau de confiance", status=403)
        try:
            body = self._read_json()
        except Exception:
            return self._error("Invalid JSON")
        if body.get("clear"):
            return self._json({"ok": True, "prefs": history_mod.clear_prefs()})
        prefs = body.get("prefs") if isinstance(body.get("prefs"), dict) else body
        if not isinstance(prefs, dict):
            return self._error("prefs invalides")
        merge = body.get("merge", True) is not False
        saved = history_mod.save_prefs(prefs, merge=merge)
        return self._json({"ok": True, "prefs": saved})

    def _handle_links_save(self) -> None:
        if not self._is_local_client():
            return self._error("Liens réservés au réseau de confiance", status=403)
        try:
            body = self._read_json()
        except Exception:
            return self._error("Invalid JSON")
        links = history_mod.save_community_links(
            tiktok=str(body.get("tiktok") or ""),
            github=str(body.get("github") or ""),
            discord=str(body.get("discord") or ""),
        )
        return self._json({"ok": True, "links": links})

    def _handle_discord_save(self) -> None:
        if not self._is_local_client():
            return self._error("Discord réservé au réseau de confiance", status=403)
        try:
            body = self._read_json()
        except Exception:
            return self._error("Invalid JSON")
        url = discord_mod.save_webhook(str(body.get("url") or ""))
        return self._json({"ok": True, "configured": bool(url)})

    def _handle_companion_config(self) -> None:
        if not self._is_local_client():
            return self._error("Companion réservé au réseau de confiance", status=403)
        try:
            body = self._read_json()
        except Exception:
            return self._error("Invalid JSON")
        enabled = body.get("enabled")
        host = body.get("host")
        port = body.get("port")
        # Default host to console IP from request/body if enabling without host
        if host is None and body.get("use_console_host"):
            host = (body.get("console_host") or DEFAULT_HOST or "").strip()
        cfg = companion_mod.save_config(
            enabled=None if enabled is None else bool(enabled),
            host=None if host is None else str(host),
            port=None if port is None else port,
        )
        return self._json({"ok": True, **companion_mod.status_payload(), "saved": cfg})

    def _handle_transfer_local(self) -> None:
        if not self._is_local_client():
            return self._error("Transfert local réservé à localhost", status=403)
        try:
            body = self._read_json()
        except Exception:
            return self._error("Invalid JSON")
        host = (body.get("host") or DEFAULT_HOST).strip()
        paths = body.get("paths") or []
        workers = body.get("workers") or xfer.DEFAULT_WORKERS
        dest_root = (body.get("dest_root") or HOMEBREW_DIR).strip()
        if not isinstance(paths, list) or not paths:
            return self._error("Missing paths")
        try:
            job = xfer.start_transfer(host, [str(p) for p in paths], dest_root=dest_root, workers=workers)
            return self._json({"ok": True, "job": job.snapshot()})
        except Exception as exc:  # noqa: BLE001
            return self._error(str(exc), status=502)

    def _handle_transfer_raw(self) -> None:
        """Stream one binary file body straight to FTP (no base64)."""
        if not self._is_local_client():
            return self._error("Upload raw réservé au réseau de confiance", status=403)
        host = (self.headers.get("X-PSHD-Host") or DEFAULT_HOST).strip()
        rel = (self.headers.get("X-PSHD-Relative-Path") or self.headers.get("X-PSHD-Filename") or "").strip()
        dest_root = (self.headers.get("X-PSHD-Dest-Root") or HOMEBREW_DIR).strip()
        length = int(self.headers.get("Content-Length") or 0)
        if not rel or length <= 0:
            return self._error("Missing path/Content-Length")
        rel = rel.replace("\\", "/").lstrip("/")
        if ".." in rel.split("/"):
            return self._error("Invalid relative path")
        try:
            dest_root = assert_writable_path(dest_root)
        except (ValueError, PermissionError) as exc:
            return self._error(str(exc))
        # Flat PKG → pkgs/; nested relative paths keep structure under dest_root
        if "/" not in rel:
            remote = xfer._remote_for_filename(dest_root, rel)
        else:
            remote = normalize_remote_path(f"{dest_root.rstrip('/')}/{rel}")
        try:
            assert_writable_path(remote)
        except (ValueError, PermissionError) as exc:
            return self._error(str(exc))

        # Stream HTTP body → FTP STOR directly (no full-disk spool). Backpressure
        # makes browser upload progress ≈ FTP speed; much faster on big files.
        import uuid as _uuid

        job = xfer.TransferJob(
            id=str(_uuid.uuid4()),
            host=host,
            total_files=1,
            total_bytes=length,
            upload_total=length,
            status="running",
            phase="upload",
            kind="transfer",
            remote_path=remote,
            current=Path(rel).name,
            workers=1,
            started_at=time.time(),
        )
        with xfer._jobs_lock:
            xfer._jobs[job.id] = job
        remaining = length

        def _read_chunk(size: int) -> bytes:
            nonlocal remaining
            if remaining <= 0:
                return b""
            chunk = self.rfile.read(min(size, remaining))
            if not chunk:
                return b""
            remaining -= len(chunk)
            return chunk

        def _on_bytes(n: int) -> None:
            with job._lock:
                job.sent_bytes += n
                job.upload_bytes += n
                job.current = f"{Path(rel).name} · {job.upload_bytes}/{job.upload_total}"
            try:
                companion_mod.notify_job_obj(job, force=False)
            except Exception:
                pass

        try:
            try:
                companion_mod.notify_job_obj(job, force=True)
            except Exception:
                pass
            sent = xfer.upload_stream(
                host,
                remote,
                _read_chunk,
                total_size=length,
                on_bytes=_on_bytes,
            )
            if remaining != 0 and sent != length:
                with job._lock:
                    job.status = "error"
                    job.phase = "error"
                    job.errors.append("Upload incomplet")
                    job.finished_at = time.time()
                try:
                    companion_mod.notify_job_obj(job, force=True)
                except Exception:
                    pass
                return self._error("Upload incomplet", status=400)
            with job._lock:
                job.status = "done"
                job.phase = "done"
                job.done_files = 1
                job.upload_bytes = max(job.upload_bytes, length)
                job.sent_bytes = max(job.sent_bytes, length)
                job.finished_at = time.time()
            try:
                companion_mod.notify_job_obj(job, force=True)
            except Exception:
                pass
            try:
                xfer._finish_job_side_effects(job)
            except Exception:
                pass
            return self._json(
                {
                    "ok": True,
                    "remote": remote,
                    "bytes": sent,
                    "dest_root": dest_root,
                    "job": job.snapshot(),
                }
            )
        except Exception as exc:  # noqa: BLE001
            with job._lock:
                job.status = "error"
                job.phase = "error"
                job.errors.append(str(exc))
                job.finished_at = time.time()
            return self._error(str(exc), status=502)

    def _handle_upload(self) -> None:
        if not self._is_local_client():
            return self._error("Upload réservé au réseau de confiance", status=403)
        try:
            body = self._read_json()
        except Exception:
            return self._error("Invalid JSON")

        host = (body.get("host") or DEFAULT_HOST).strip()
        filename = Path((body.get("filename") or "").strip()).name
        raw_b64 = body.get("data_base64") or ""
        if not filename:
            return self._error("Missing filename")
        if not raw_b64:
            return self._error("Missing data_base64")

        try:
            data = base64.b64decode(raw_b64, validate=False)
        except Exception:
            return self._error("Invalid base64 payload")
        if not data:
            return self._error("Empty file")

        remote = xfer._remote_for_filename(HOMEBREW_DIR, filename)
        try:
            with ftp_connect(host) as ftp:
                ftp_upload_bytes(ftp, remote, data)
            digest = hashlib.sha256(data).hexdigest()
            return self._json(
                {
                    "ok": True,
                    "remote": remote,
                    "bytes": len(data),
                    "sha256": digest,
                }
            )
        except Exception as exc:  # noqa: BLE001
            return self._error(str(exc), status=502)

    def _serve_catalog_file(self, path: str) -> None:
        name = Path(path).name
        if not name or name != Path(name).name or ".." in path:
            return self._error("Fichier invalide", status=400)
        target = (CATALOG_FILES / name).resolve()
        try:
            target.relative_to(CATALOG_FILES.resolve())
        except ValueError:
            return self._error("Chemin interdit", status=403)
        if not target.is_file():
            return self._error("Introuvable", status=404)
        data = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _serve_updates(self, path: str) -> None:
        name = Path(path).name
        if not name or name != Path(name).name or ".." in path:
            return self._error("Fichier invalide", status=400)
        UPDATES_DIR.mkdir(parents=True, exist_ok=True)
        target = (UPDATES_DIR / name).resolve()
        try:
            target.relative_to(UPDATES_DIR.resolve())
        except ValueError:
            return self._error("Chemin interdit", status=403)
        if not target.is_file():
            return self._error("Mise à jour introuvable — publie-en une d’abord", status=404)
        data = target.read_bytes()
        ctype = "application/json" if name.endswith(".json") else "application/zip"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Disposition", f'attachment; filename="{name}"')
        self.end_headers()
        self.wfile.write(data)

    def _handle_publish_update(self) -> None:
        if not self._is_local_client():
            return self._error("Publication réservée au réseau de confiance", status=403)
        try:
            body = self._read_json()
        except Exception:
            body = {}
        notes = str(body.get("notes") or "").strip()
        try:
            from desk.update_channel import build_update_zip

            manifest = build_update_zip(notes=notes)
            discord_result = {}
            if body.get("discord", True):
                try:
                    discord_result = discord_mod.post_update(manifest)
                except Exception as exc:  # noqa: BLE001
                    discord_result = {"ok": False, "error": str(exc)}
            return self._json({"ok": True, "manifest": manifest, "discord": discord_result})
        except Exception as exc:  # noqa: BLE001
            return self._error(str(exc), status=502)

    def _handle_eden_status(self, host: str) -> None:
        try:
            with ftp_connect(host) as ftp:
                return self._json(eden_mod.status(ftp))
        except Exception as exc:  # noqa: BLE001
            return self._error(str(exc), status=502)

    def _handle_eden_release(self) -> None:
        try:
            return self._json(eden_mod.latest_release())
        except Exception as exc:  # noqa: BLE001
            return self._error(str(exc), status=502)

    def _handle_eden_install(self) -> None:
        if not self._is_local_client():
            return self._error("Install Eden réservée au réseau de confiance", status=403)
        try:
            body = self._read_json()
        except Exception:
            body = {}
        host = (body.get("host") or DEFAULT_HOST or "").strip()
        if not host:
            return self._error("IP console manquante")
        try:
            rel = eden_mod.latest_release()
            url = str(body.get("url") or rel.get("url") or "").strip()
            filename = str(body.get("filename") or rel.get("filename") or "ProsperoEden.zip")
            if not url:
                return self._error("URL release introuvable")
            job = xfer.start_url_transfer(
                host,
                url,
                filename=filename,
                dest_root=HOMEBREW_DIR,
                extract=True,
            )
            return self._json({"ok": True, "job": job.snapshot(), "release": rel})
        except Exception as exc:  # noqa: BLE001
            return self._error(str(exc), status=502)

    def _handle_eden_push(self) -> None:
        if not self._is_local_client():
            return self._error("Push Eden réservé au réseau de confiance", status=403)
        try:
            body = self._read_json()
        except Exception:
            return self._error("Invalid JSON")
        host = (body.get("host") or DEFAULT_HOST or "").strip()
        kind = str(body.get("kind") or "").strip().lower()
        paths = body.get("paths") if isinstance(body.get("paths"), list) else []
        if not host:
            return self._error("IP console manquante")
        try:
            dest = assert_writable_path(eden_mod.dest_for_kind(kind))
            clean = eden_mod.validate_paths_for_kind(kind, [str(p) for p in paths])
            job = xfer.start_transfer(host, clean, dest_root=dest)
            return self._json({"ok": True, "job": job.snapshot(), "dest_root": dest, "kind": kind})
        except Exception as exc:  # noqa: BLE001
            return self._error(str(exc), status=502)

    def _handle_eden_delete_rom(self) -> None:
        if not self._is_local_client():
            return self._error("Suppression réservée au réseau de confiance", status=403)
        try:
            body = self._read_json()
        except Exception:
            return self._error("Invalid JSON")
        host = (body.get("host") or DEFAULT_HOST or "").strip()
        try:
            remote = eden_mod.assert_rom_path(str(body.get("path") or ""))
            remote = assert_writable_path(remote)
        except (ValueError, PermissionError) as exc:
            return self._error(str(exc))
        try:
            with ftp_connect(host) as ftp:
                ftp_delete(ftp, remote, is_dir=False)
            return self._json({"ok": True, "path": remote})
        except Exception as exc:  # noqa: BLE001
            return self._error(str(exc), status=502)

    def _handle_orbit_status(self, host: str) -> None:
        try:
            with ftp_connect(host) as ftp:
                return self._json(orbit_mod.status(ftp, host))
        except Exception as exc:  # noqa: BLE001
            # FTP down — still report web port if possible
            online = orbit_mod.probe_port(host) if host else False
            return self._json(
                {
                    "ok": True,
                    "ftp_error": str(exc),
                    "installed": False,
                    "dir_present": False,
                    "elf": None,
                    "port": orbit_mod.ORBIT_PORT,
                    "online": online,
                    "url": f"http://{host}:{orbit_mod.ORBIT_PORT}/" if host else "",
                    "orbit_dir": orbit_mod.ORBIT_DIR,
                    "elf_path": orbit_mod.ORBIT_ELF_PATH,
                    "github": f"https://github.com/{orbit_mod.GITHUB_REPO}",
                }
            )

    def _handle_orbit_release(self) -> None:
        try:
            return self._json(orbit_mod.latest_release())
        except Exception as exc:  # noqa: BLE001
            return self._error(str(exc), status=502)

    def _handle_open_external(self) -> None:
        """Open http(s) URL in the OS default browser (Desk window can't window.open)."""
        if not self._is_local_client():
            return self._error("Ouverture réservée au réseau de confiance", status=403)
        try:
            body = self._read_json()
        except Exception:
            return self._error("Invalid JSON")
        url = str(body.get("url") or "").strip()
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            return self._error("URL http(s) requise")
        host_l = (parsed.hostname or "").lower()
        # Allow LAN console / local only — block obvious SSRF to metadata
        if host_l in ("metadata.google.internal",) or host_l.startswith("169.254.169.254"):
            return self._error("URL non autorisée")
        try:
            opened = webbrowser.open(url)
            if not opened:
                plat = sys.platform
                if plat == "darwin":
                    import subprocess

                    subprocess.run(["open", url], check=False)
                    opened = True
                elif plat.startswith("win"):
                    os.startfile(url)  # type: ignore[attr-defined]
                    opened = True
            return self._json({"ok": True, "opened": bool(opened), "url": url})
        except Exception as exc:  # noqa: BLE001
            return self._error(str(exc), status=502)

    def _handle_orbit_install(self) -> None:
        if not self._is_local_client():
            return self._error("Install Orbit réservée au réseau de confiance", status=403)
        try:
            body = self._read_json()
        except Exception:
            body = {}
        host = (body.get("host") or DEFAULT_HOST or "").strip()
        if not host:
            return self._error("IP console manquante — Connecter d’abord")
        force = bool(body.get("force"))
        try:
            local_elf, rel = orbit_mod.ensure_local_elf(PAYLOADS_DIR, force=force)
        except Exception as exc:  # noqa: BLE001
            return self._error(f"Téléchargement Orbit: {exc}", status=502)
        warning = ""
        dest = orbit_mod.ORBIT_DIR
        try:
            dest = assert_writable_path(dest)
            job = xfer.start_transfer(host, [str(local_elf)], dest_root=dest, workers=1)
        except Exception as exc:  # noqa: BLE001
            # Fallback: /data/homebrew if orbit-store path rejected / FTP mkdir fails at start
            try:
                dest = assert_writable_path(orbit_mod.ORBIT_FALLBACK_DIR)
                job = xfer.start_transfer(host, [str(local_elf)], dest_root=dest, workers=1)
                warning = f"Fallback → {dest} ({exc})"
            except Exception as exc2:  # noqa: BLE001
                return self._error(f"Upload Orbit: {exc2}", status=502)
        return self._json(
            {
                "ok": True,
                "job": job.snapshot(),
                "release": rel,
                "dest_root": dest,
                "local": str(local_elf),
                "bytes": local_elf.stat().st_size,
                "warning": warning,
            }
        )

    def _handle_orbit_elfldr(self) -> None:
        if not self._is_local_client():
            return self._error("elfldr réservé au réseau de confiance", status=403)
        try:
            body = self._read_json()
        except Exception:
            body = {}
        host = (body.get("host") or DEFAULT_HOST or "").strip()
        if not host:
            return self._error("IP console manquante — Connecter d’abord")
        port = int(body.get("port") or ELFLDR_PORT)
        force = bool(body.get("force"))
        filename = orbit_mod.ORBIT_ELF_NAME
        try:
            local_elf, rel = orbit_mod.ensure_local_elf(PAYLOADS_DIR, force=force)
            data = local_elf.read_bytes()
            result = send_elf_to_loader(host, data, port=port)
            return self._json(
                {
                    "ok": True,
                    "send": result,
                    "filename": filename,
                    "bytes": len(data),
                    "release": rel,
                    "local": str(local_elf),
                }
            )
        except Exception as exc:  # noqa: BLE001
            return self._error(str(exc), status=502)

    def _handle_games_list(self, host: str) -> None:
        try:
            with ftp_connect(host) as ftp:
                items = games_mod.scan_games(ftp)
            return self._json(
                {
                    "ok": True,
                    "count": len(items),
                    "roots": list(games_mod.SCAN_ROOTS),
                    "games": items,
                }
            )
        except Exception as exc:  # noqa: BLE001
            return self._error(str(exc), status=502)

    def _handle_games_info(self, host: str, qs: Dict[str, List[str]]) -> None:
        path = (qs.get("path") or [""])[0].strip()
        if not path:
            return self._error("Missing path")
        try:
            with ftp_connect(host) as ftp:
                info = games_mod.game_info(ftp, path)
            return self._json({"ok": True, "game": info})
        except FileNotFoundError as exc:
            return self._error(str(exc), status=404)
        except Exception as exc:  # noqa: BLE001
            return self._error(str(exc), status=502)

    def _handle_games_icon(self, host: str, qs: Dict[str, List[str]]) -> None:
        icon_path = (qs.get("icon_path") or qs.get("path") or [""])[0].strip()
        title_id = (qs.get("title_id") or ["GAME"])[0].strip().upper() or "GAME"
        if not icon_path:
            return self._error("Missing icon_path", status=404)
        # Browsers can't display DDS — skip and let UI placeholder show
        if icon_path.lower().endswith(".dds"):
            return self._error("DDS non supporté", status=415)
        # Serve from local cache when present
        safe_tid = re.sub(r"[^A-Z0-9_\-]", "_", title_id)[:32]
        cache = ROOT / games_mod.CACHE_DIR_NAME / f"{safe_tid}.png"
        if cache.is_file() and cache.stat().st_size > 0:
            data = cache.read_bytes()
        else:
            try:
                with ftp_connect(host) as ftp:
                    data = games_mod.fetch_icon_bytes(ftp, icon_path)
                # Reject non-PNG payloads cached by mistake
                if not data.startswith(b"\x89PNG") and icon_path.lower().endswith(".png"):
                    pass
                if data[:4] in (b"DDS ",) or icon_path.lower().endswith(".dds"):
                    return self._error("DDS non supporté", status=415)
                games_mod.cache_icon(ROOT, title_id, data, suffix=".png")
            except Exception as exc:  # noqa: BLE001
                return self._error(str(exc), status=404)
        self.send_response(200)
        self.send_header("Content-Type", "image/png")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "public, max-age=86400")
        self.end_headers()
        self.wfile.write(data)

    def _handle_games_uninstall(self) -> None:
        if not self._is_local_client():
            return self._error("Désinstallation réservée au réseau de confiance", status=403)
        try:
            body = self._read_json()
        except Exception:
            return self._error("Invalid JSON")
        host = (body.get("host") or DEFAULT_HOST).strip()
        path = (body.get("path") or "").strip()
        title_id = str(body.get("title_id") or "").strip().upper()
        confirm = str(body.get("confirm") or "").strip().upper()
        if not path:
            return self._error("Missing path")
        if confirm != title_id or not title_id:
            return self._error("Confirmation invalide — renvoie confirm=TITLEID")
        try:
            path = normalize_remote_path(path)
            assert_writable_path(path)
        except (ValueError, PermissionError) as exc:
            return self._error(str(exc))
        if not games_mod._can_uninstall(path, title_id):
            return self._error("Désinstallation bloquée pour ce titre/chemin", status=403)
        try:
            with ftp_connect(host) as ftp:
                is_dir = ftp_is_dir(ftp, path)
                # Safety: folder uninstall must contain title id in path or param
                if is_dir:
                    info = games_mod.game_info(ftp, path)
                    if str(info.get("title_id") or "").upper() != title_id:
                        return self._error("TITLEID ne correspond pas au dossier", status=409)
                ftp_delete(ftp, path, is_dir=is_dir)
            # Drop cached icon
            cache = ROOT / games_mod.CACHE_DIR_NAME / f"{title_id}.png"
            if cache.is_file():
                try:
                    cache.unlink()
                except OSError:
                    pass
            return self._json({"ok": True, "deleted": path, "title_id": title_id})
        except Exception as exc:  # noqa: BLE001
            return self._error(str(exc), status=502)

    def _fetch_catalog_or_url(self, url: str) -> bytes:
        """Resolve local catalog mirror paths or download remote URLs."""
        parsed = urlparse(url)
        rel = parsed.path if url.startswith("/") else parsed.path
        if url.startswith("/catalog/files/") or rel.startswith("/catalog/files/"):
            name = Path(rel).name
            target = (CATALOG_FILES / name).resolve()
            target.relative_to(CATALOG_FILES.resolve())
            if not target.is_file():
                raise FileNotFoundError(name)
            return target.read_bytes()
        # Also accept absolute local desk URLs
        if parsed.scheme in ("http", "https") and parsed.hostname in ("127.0.0.1", "localhost"):
            if parsed.path.startswith("/catalog/files/"):
                return self._fetch_catalog_or_url(parsed.path)
        with urllib.request.urlopen(url, timeout=90) as resp:
            return resp.read()

    def _handle_install(self) -> None:
        if not self._is_local_client():
            return self._error("Install catalogue réservé au réseau de confiance", status=403)
        try:
            body = self._read_json()
        except Exception:
            return self._error("Invalid JSON")

        host = (body.get("host") or DEFAULT_HOST).strip()
        url = (body.get("url") or "").strip()
        filename = (body.get("filename") or "").strip()
        expected = (body.get("sha256") or "").strip().lower()

        if not url:
            return self._error("Missing url")
        if not filename:
            filename = Path(urlparse(url).path).name or "payload.bin"
        filename = Path(filename).name
        # Only allow local catalog mirrors or https GitHub/release URLs
        if not (
            url.startswith("/catalog/files/")
            or url.startswith("https://github.com/")
            or url.startswith("https://objects.githubusercontent.com/")
            or url.startswith("http://127.0.0.1:")
            or url.startswith("http://localhost:")
        ):
            parsed = urlparse(url)
            if parsed.scheme not in ("http", "https") or not parsed.netloc:
                return self._error("URL non autorisée")
            # Block obvious SSRF targets
            host_l = (parsed.hostname or "").lower()
            if host_l in ("127.0.0.1", "localhost", "0.0.0.0", "::1") and not url.startswith(
                ("http://127.0.0.1:", "http://localhost:")
            ):
                return self._error("URL non autorisée")
            if host_l.startswith("169.254.") or host_l.endswith(".local"):
                return self._error("URL non autorisée")

        try:
            data = self._fetch_catalog_or_url(url)
        except Exception as exc:  # noqa: BLE001
            return self._error(f"Download failed: {exc}", status=502)

        digest = hashlib.sha256(data).hexdigest()
        if expected and digest != expected:
            return self._error(f"SHA-256 mismatch: got {digest}", status=400)

        remote = xfer._remote_for_filename(HOMEBREW_DIR, filename)
        try:
            with ftp_connect(host) as ftp:
                ftp_upload_bytes(ftp, remote, data)
            return self._json(
                {
                    "ok": True,
                    "remote": remote,
                    "bytes": len(data),
                    "sha256": digest,
                    "source": url,
                }
            )
        except Exception as exc:  # noqa: BLE001
            return self._error(str(exc), status=502)

    def _handle_elfs_list(self, host: str) -> None:
        catalog = load_catalog()
        try:
            if probe_port(host, FTP_PORT, timeout=0.8):
                with ftp_connect(host) as ftp:
                    items = elfs_mod.scan_all(ftp, catalog, PAYLOADS_DIR)
            else:
                items = elfs_mod.scan_all(None, catalog, PAYLOADS_DIR)
            return self._json(
                {
                    "ok": True,
                    "roots": list(elfs_mod.SCAN_ROOTS),
                    "elfs": items,
                    "updates": sum(1 for e in items if e.get("update_available")),
                    "ftp": probe_port(host, FTP_PORT, timeout=0.4),
                }
            )
        except Exception as exc:  # noqa: BLE001
            return self._error(str(exc), status=502)

    def _handle_elfs_info(self, host: str, qs: Dict[str, List[str]]) -> None:
        path = (qs.get("path") or [""])[0].strip()
        if not path:
            return self._error("Missing path")
        catalog = load_catalog()
        index = elfs_mod.build_catalog_index(catalog)
        if path.startswith("local:"):
            name = path.split(":", 1)[1]
            local = (PAYLOADS_DIR / Path(name).name).resolve()
            if not str(local).startswith(str(PAYLOADS_DIR.resolve()) + os.sep) or not local.is_file():
                return self._error("ELF local introuvable", status=404)
            info = elfs_mod.enrich_elf(
                filename=local.name,
                path=f"local:{local.name}",
                size=local.stat().st_size,
                index=index,
                location="local",
            )
            info["local_path"] = str(local)
            return self._json({"ok": True, "elf": info})
        try:
            path = normalize_remote_path(path)
            parent = remote_parent(path)
            name = remote_name(path)
            with ftp_connect(host) as ftp:
                size = 0
                for e in ftp_list(ftp, parent if parent.startswith("/") else "/" + parent):
                    if e["name"] == name:
                        size = int(e.get("size") or 0)
                        break
                else:
                    return self._error("ELF introuvable", status=404)
            info = elfs_mod.enrich_elf(
                filename=name, path=path, size=size, index=index, location="console"
            )
            return self._json({"ok": True, "elf": info})
        except Exception as exc:  # noqa: BLE001
            return self._error(str(exc), status=502)

    def _handle_elfs_uninstall(self) -> None:
        if not self._is_local_client():
            return self._error("Désinstallation réservée au réseau de confiance", status=403)
        try:
            body = self._read_json()
        except Exception:
            return self._error("Invalid JSON")
        host = (body.get("host") or DEFAULT_HOST).strip()
        path = (body.get("path") or "").strip()
        filename = str(body.get("filename") or remote_name(path)).strip()
        confirm = str(body.get("confirm") or "").strip()
        if not path:
            return self._error("Missing path")
        if confirm.lower() != filename.lower():
            return self._error("Confirmation invalide — renvoie confirm=filename")
        if path.startswith("local:"):
            name = Path(path.split(":", 1)[1]).name
            local = (PAYLOADS_DIR / name).resolve()
            if not str(local).startswith(str(PAYLOADS_DIR.resolve()) + os.sep):
                return self._error("Chemin local invalide", status=400)
            if local.is_file():
                local.unlink()
            return self._json({"ok": True, "deleted": f"local:{name}", "filename": name})
        try:
            path = normalize_remote_path(path)
            assert_writable_path(path)
        except (ValueError, PermissionError) as exc:
            return self._error(str(exc))
        if not path.lower().endswith(".elf"):
            return self._error("Seul un fichier .elf peut être désinstallé ici", status=400)
        if not elfs_mod._can_uninstall(path):
            return self._error("Désinstallation bloquée pour ce chemin", status=403)
        try:
            with ftp_connect(host) as ftp:
                ftp_delete(ftp, path, is_dir=False)
            return self._json({"ok": True, "deleted": path, "filename": filename})
        except Exception as exc:  # noqa: BLE001
            return self._error(str(exc), status=502)

    def _handle_elfs_update(self) -> None:
        """One-click update from catalog mirror (no manual re-download)."""
        if not self._is_local_client():
            return self._error("Mise à jour réservée au réseau de confiance", status=403)
        try:
            body = self._read_json()
        except Exception:
            return self._error("Invalid JSON")
        host = (body.get("host") or DEFAULT_HOST).strip()
        path = (body.get("path") or "").strip()
        update_url = (body.get("update_url") or "").strip()
        update_filename = (body.get("update_filename") or "").strip()
        expected = (body.get("update_sha256") or body.get("sha256") or "").strip().lower()
        remove_old = bool(body.get("remove_old", True))

        catalog = load_catalog()
        index = elfs_mod.build_catalog_index(catalog)
        # Resolve update target from path if ids not provided
        if path and (not update_url or not update_filename):
            name = Path(path.split(":", 1)[-1]).name
            _match, newest = elfs_mod.match_catalog(name, index)
            if not newest:
                return self._error("Aucune mise à jour catalogue pour cet ELF")
            update_url = update_url or newest.get("url") or ""
            update_filename = update_filename or newest.get("filename") or ""
            expected = expected or (newest.get("sha256") or "").lower()

        if not update_url or not update_filename:
            return self._error("update_url / update_filename manquants")
        update_filename = Path(update_filename).name

        try:
            data = self._fetch_catalog_or_url(update_url)
        except Exception as exc:  # noqa: BLE001
            return self._error(f"Téléchargement MAJ échoué: {exc}", status=502)
        digest = hashlib.sha256(data).hexdigest()
        if expected and digest != expected:
            return self._error(f"SHA-256 mismatch: got {digest}", status=400)

        # Local payload update
        if path.startswith("local:"):
            dest = (PAYLOADS_DIR / update_filename).resolve()
            if not str(dest).startswith(str(PAYLOADS_DIR.resolve()) + os.sep):
                return self._error("Chemin local invalide", status=400)
            PAYLOADS_DIR.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
            old_name = Path(path.split(":", 1)[1]).name
            if remove_old and old_name.lower() != update_filename.lower():
                old = (PAYLOADS_DIR / old_name).resolve()
                if old.is_file() and str(old).startswith(str(PAYLOADS_DIR.resolve()) + os.sep):
                    try:
                        old.unlink()
                    except OSError:
                        pass
            return self._json(
                {
                    "ok": True,
                    "remote": f"local:{update_filename}",
                    "bytes": len(data),
                    "sha256": digest,
                    "filename": update_filename,
                }
            )

        # Console FTP update — keep same folder when possible
        try:
            old_path = normalize_remote_path(path) if path else ""
            if old_path:
                parent = remote_parent(old_path)
                if not parent.startswith("/"):
                    parent = "/" + parent
            else:
                parent = HOMEBREW_DIR
            assert_writable_path(parent)
            remote = normalize_remote_path(f"{parent.rstrip('/')}/{update_filename}")
            assert_writable_path(remote)
        except (ValueError, PermissionError) as exc:
            return self._error(str(exc))

        try:
            with ftp_connect(host) as ftp:
                ftp_upload_bytes(ftp, remote, data)
                if (
                    remove_old
                    and old_path
                    and old_path.lower() != remote.lower()
                    and old_path.lower().endswith(".elf")
                ):
                    try:
                        ftp_delete(ftp, old_path, is_dir=False)
                    except Exception:
                        pass
            return self._json(
                {
                    "ok": True,
                    "remote": remote,
                    "bytes": len(data),
                    "sha256": digest,
                    "filename": update_filename,
                    "replaced": old_path if old_path and old_path.lower() != remote.lower() else "",
                }
            )
        except Exception as exc:  # noqa: BLE001
            return self._error(str(exc), status=502)


def _safe_print(msg: str) -> None:
    """Windows consoles are often cp1252 — never crash the server on a glyph."""
    try:
        print(msg)
    except UnicodeEncodeError:
        enc = getattr(sys.stdout, "encoding", None) or "ascii"
        print(msg.encode(enc, errors="replace").decode(enc, errors="replace"))


class DeskHTTPServer(ThreadingHTTPServer):
    """Reusable bind helps Windows relaunch after crash / double-click."""

    allow_reuse_address = True
    daemon_threads = True


def main() -> None:
    configure_stdio()
    host = desk_bind_host()
    port = desk_port()
    STATIC.mkdir(parents=True, exist_ok=True)
    UPDATES_DIR.mkdir(parents=True, exist_ok=True)
    PAYLOADS_DIR.mkdir(parents=True, exist_ok=True)
    try:
        server = DeskHTTPServer((host, port), DeskHandler)
    except OSError as exc:
        raise SystemExit(
            f"Impossible d'ouvrir le port {port} ({host}): {exc}\n"
            "Ferme l'autre instance de PS Homebrew Desk, ou change DESK_PORT."
        ) from exc
    info = desk_runtime_info()
    _safe_print(f"PS Homebrew Desk v{info['version']} by {app_author()} ({info['platform']})")
    _safe_print(f"Local  -> http://127.0.0.1:{port}")
    if lan_enabled() or host in ("0.0.0.0", "::"):
        _safe_print(f"LAN    -> {info['lan_url']}")
        _safe_print("iPhone -> Safari -> partager -> Sur l'ecran d'accueil")
        if desk_token():
            _safe_print("Token  -> DESK_TOKEN actif (header X-PSHD-Token)")
    _safe_print("Writable: /data, /user, /mnt - system paths are read-only.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        _safe_print("\nStopped.")


if __name__ == "__main__":
    main()
