"""Detect PS5 games on the console over FTP (installed, homebrew, USB, images)."""

from __future__ import annotations

import json
import re
import struct
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
from ftplib import FTP, error_perm
from io import BytesIO

TITLE_RE = re.compile(r"^[A-Z]{4}\d{5}$")
TITLE_IN_NAME_RE = re.compile(r"([A-Z]{4}\d{5})", re.I)
IMAGE_SUFFIXES = {".ffpkg", ".exfat", ".ffpfs", ".ffpfsc", ".iso", ".pkg", ".fpkg"}
# Prefer PNG only — DDS is not displayable in the Desk browser UI
ICON_CANDIDATES = ("icon0.png", "pic0.png", "pic1.png")
PARAM_CANDIDATES = ("param.json", "param.sfo")

# Where games commonly live on a jailbroken PS5
SCAN_ROOTS = (
    "/user/app",
    "/user/homebrew",
    "/homebrew",
    "/data/homebrew",
    "/data/homebrew/games",
    "/data/homebrew/pkgs",
    "/mnt/usb0",
    "/mnt/usb1",
    "/mnt/ext0",
    "/usb0",
    "/usb1",
)

# Never offer uninstall for these title prefixes (system / HEN tooling)
BLOCKED_UNINSTALL_PREFIXES = (
    "NPXS",
    "NPXX",
    "ITEM",
    "ETHN",
    "LAPY",  # common payload title ids — still allow if user insists? keep blocked for safety
)

CACHE_DIR_NAME = "cache/game-icons"


def is_title_id(name: str) -> bool:
    return bool(TITLE_RE.match((name or "").strip().upper()))


def title_from_name(name: str) -> str:
    m = TITLE_IN_NAME_RE.search((name or "").upper())
    return m.group(1) if m else ""


def parse_param_json(text: str) -> Dict[str, Any]:
    try:
        data = json.loads(text)
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}
    title_id = str(data.get("titleId") or data.get("TITLEID") or data.get("title_id") or "").upper()
    content_id = str(data.get("contentId") or data.get("CONTENT_ID") or "")
    title_name = str(data.get("titleName") or data.get("TITLE") or "")
    loc = data.get("localizedParameters") or data.get("localizedParam") or {}
    if isinstance(loc, dict) and not title_name:
        default_lang = loc.get("defaultLanguage") or loc.get("defaultLanguageCode")
        if isinstance(default_lang, str) and isinstance(loc.get(default_lang), dict):
            title_name = str(loc[default_lang].get("titleName") or loc[default_lang].get("title") or "")
        if not title_name:
            for key, val in loc.items():
                if key in ("defaultLanguage", "defaultLanguageCode"):
                    continue
                if isinstance(val, dict):
                    title_name = str(val.get("titleName") or val.get("title") or "")
                    if title_name:
                        break
    if not title_id and content_id:
        title_id = title_from_name(content_id)
    return {
        "title_id": title_id,
        "content_id": content_id,
        "title_name": title_name,
        "raw": data,
        "param_source": "param.json",
    }


def parse_param_sfo(data: bytes) -> Dict[str, Any]:
    """Parse binary param.sfo (PS4/PS5 PSF) for TITLE / TITLE_ID / CONTENT_ID."""
    if not data or len(data) < 20 or data[:4] != b"\x00PSF":
        return {}
    try:
        _magic, _ver, key_table_start, data_table_start, n_entries = struct.unpack_from("<IIIII", data, 0)
    except struct.error:
        return {}
    if n_entries <= 0 or n_entries > 512:
        return {}
    if key_table_start >= len(data) or data_table_start >= len(data):
        return {}

    values: Dict[str, Any] = {}
    for i in range(n_entries):
        off = 20 + i * 16
        if off + 16 > len(data):
            break
        key_off, data_fmt, data_len, _data_max, data_off = struct.unpack_from("<HHIII", data, off)
        k0 = key_table_start + key_off
        if k0 >= len(data):
            continue
        k1 = data.find(b"\x00", k0)
        if k1 < 0:
            k1 = min(len(data), k0 + 64)
        key = data[k0:k1].decode("ascii", errors="replace")
        d0 = data_table_start + data_off
        d1 = min(len(data), d0 + max(0, data_len))
        blob = data[d0:d1]
        fmt = data_fmt & 0xFFFC
        if fmt in (0x0004, 0x0204):  # utf8 / utf8-special
            text = blob.split(b"\x00", 1)[0].decode("utf-8", errors="replace").strip()
            values[key] = text
        elif fmt == 0x0404 and len(blob) >= 4:  # int32
            values[key] = struct.unpack_from("<I", blob, 0)[0]
        else:
            values[key] = blob

    title_id = str(values.get("TITLE_ID") or values.get("TITLEID") or "").upper().strip()
    content_id = str(values.get("CONTENT_ID") or "").strip()
    title_name = str(values.get("TITLE") or values.get("APP_VER") or "").strip()
    if not title_id and content_id:
        title_id = title_from_name(content_id)
    if not title_name:
        title_name = title_id
    if not title_id and not title_name and not content_id:
        return {}
    return {
        "title_id": title_id,
        "content_id": content_id,
        "title_name": title_name,
        "raw": {k: v for k, v in values.items() if isinstance(v, (str, int))},
        "param_source": "param.sfo",
    }


def _ftp_read_bytes(ftp: FTP, path: str, limit: int = 2_000_000) -> bytes:
    buf = BytesIO()
    total = 0

    def _cb(data: bytes) -> None:
        nonlocal total
        if total >= limit:
            return
        take = data[: max(0, limit - total)]
        buf.write(take)
        total += len(take)

    ftp.retrbinary(f"RETR {path}", _cb)
    return buf.getvalue()


def _ftp_exists_file(ftp: FTP, path: str) -> bool:
    parent = str(Path(path).parent.as_posix())
    name = Path(path).name
    if not parent.startswith("/"):
        parent = "/" + parent
    try:
        for e in _safe_list(ftp, parent):
            if e["name"] == name and e["type"] == "file":
                return True
    except Exception:
        return False
    return False


def _safe_list(ftp: FTP, path: str) -> List[Dict[str, Any]]:
    entries: List[Dict[str, Any]] = []
    try:
        ftp.cwd(path)
    except Exception:
        return []
    lines: List[str] = []
    try:
        ftp.retrlines("LIST", lines.append)
    except Exception:
        return []
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
            }
        )
    return entries


def _join(parent: str, name: str) -> str:
    parent = parent.rstrip("/") or ""
    if not parent:
        return "/" + name
    return f"{parent}/{name}"


def _detect_game_dir(ftp: FTP, path: str, name: str) -> Optional[Dict[str, Any]]:
    """If path looks like a game folder, return metadata."""
    sce = _join(path, "sce_sys")
    entries = _safe_list(ftp, sce)
    if not entries:
        # Some dumps nest sce_sys one level deeper
        return None
    names = {e["name"].lower(): e for e in entries}
    meta: Dict[str, Any] = {}
    for candidate in PARAM_CANDIDATES:
        if candidate not in names or names[candidate]["type"] != "file":
            continue
        try:
            raw = _ftp_read_bytes(ftp, _join(sce, candidate), limit=256_000)
        except Exception:
            continue
        if candidate.endswith(".json"):
            meta = parse_param_json(raw.decode("utf-8", errors="replace"))
        elif candidate.endswith(".sfo"):
            meta = parse_param_sfo(raw)
        if meta.get("title_id") or meta.get("title_name") or meta.get("content_id"):
            break
        meta = {}
    title_id = meta.get("title_id") or (name.upper() if is_title_id(name) else title_from_name(name))
    if not title_id and not meta:
        # sce_sys exists but no title — still treat as game-like if icon present
        if not any(c in names for c in ICON_CANDIDATES):
            return None
        title_id = name.upper() if is_title_id(name) else title_from_name(name) or name
    title_name = meta.get("title_name") or title_id or name
    icon_rel = ""
    for candidate in ICON_CANDIDATES:
        if candidate in names and names[candidate]["type"] == "file":
            icon_rel = f"sce_sys/{candidate}"
            break
    return {
        "title_id": str(title_id).upper(),
        "title_name": title_name,
        "content_id": meta.get("content_id") or "",
        "path": path,
        "kind": "folder",
        "icon_path": _join(path, icon_rel) if icon_rel else "",
        "has_param": bool(meta),
        "param_source": meta.get("param_source") or "",
        "source": _source_label(path),
        "size": 0,
        "can_uninstall": _can_uninstall(path, str(title_id).upper()),
    }


def _source_label(path: str) -> str:
    p = path.replace("\\", "/")
    if p.startswith("/user/app"):
        return "installé (/user/app)"
    if "/mnt/usb" in p or p.startswith("/usb"):
        return "USB"
    if "/homebrew" in p:
        return "homebrew"
    if p.startswith("/data"):
        return "data"
    if p.startswith("/user"):
        return "user"
    return "autre"


def _can_uninstall(path: str, title_id: str) -> bool:
    p = path.replace("\\", "/")
    if not p.startswith(("/user/", "/data/", "/mnt/", "/usb", "/homebrew")):
        return False
    if p.rstrip("/") in (
        "/user",
        "/data",
        "/user/app",
        "/user/homebrew",
        "/data/homebrew",
        "/homebrew",
        "/mnt",
    ):
        return False
    tid = (title_id or "").upper()
    for prefix in BLOCKED_UNINSTALL_PREFIXES:
        if tid.startswith(prefix):
            return False
    return True


def _detect_image_file(path: str, name: str, size: int) -> Optional[Dict[str, Any]]:
    lower = name.lower()
    if not any(lower.endswith(suf) for suf in IMAGE_SUFFIXES):
        return None
    tid = title_from_name(name)
    stem = Path(name).stem
    return {
        "title_id": tid or stem.upper()[:10],
        "title_name": stem,
        "content_id": "",
        "path": path,
        "kind": "image",
        "icon_path": "",
        "has_param": False,
        "source": _source_label(path),
        "size": size,
        "can_uninstall": _can_uninstall(path, tid),
        "image_type": Path(name).suffix.lower().lstrip("."),
    }


def scan_games(ftp: FTP, roots: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """Scan console for games. Deduplicate by title_id+path."""
    roots = roots or list(SCAN_ROOTS)
    found: List[Dict[str, Any]] = []
    seen_paths: Set[str] = set()

    def add(game: Optional[Dict[str, Any]]) -> None:
        if not game:
            return
        key = game["path"]
        if key in seen_paths:
            return
        seen_paths.add(key)
        found.append(game)

    for root in roots:
        entries = _safe_list(ftp, root)
        if not entries:
            continue
        for entry in entries:
            name = entry["name"]
            path = _join(root, name)
            if entry["type"] == "dir":
                # Direct game folder
                game = _detect_game_dir(ftp, path, name)
                if game:
                    add(game)
                    continue
                # One level deeper (e.g. /data/homebrew/Something/PPSA… or folder dumps)
                deep_roots = (
                    "/data/homebrew",
                    "/user/homebrew",
                    "/homebrew",
                    "/mnt/usb0",
                    "/mnt/usb1",
                    "/mnt/ext0",
                    "/usb0",
                    "/usb1",
                )
                if root.rstrip("/") in deep_roots:
                    for child in _safe_list(ftp, path):
                        cpath = _join(path, child["name"])
                        if child["type"] == "dir":
                            add(_detect_game_dir(ftp, cpath, child["name"]))
                        else:
                            add(_detect_image_file(cpath, child["name"], child.get("size") or 0))
            else:
                add(_detect_image_file(path, name, entry.get("size") or 0))

    # Prefer folders over bare images for same title_id when paths differ
    found.sort(key=lambda g: (g.get("title_name") or g.get("title_id") or "").lower())
    return found


def game_info(ftp: FTP, path: str) -> Dict[str, Any]:
    path = path.replace("\\", "/").rstrip("/") or path
    parent = str(Path(path).parent.as_posix())
    name = Path(path).name
    # File image?
    listing = _safe_list(ftp, parent if parent.startswith("/") else "/" + parent)
    for e in listing:
        if e["name"] == name and e["type"] == "file":
            img = _detect_image_file(path, name, e.get("size") or 0)
            if img:
                img["files_sample"] = [name]
                return img
    game = _detect_game_dir(ftp, path, name)
    if not game:
        raise FileNotFoundError(f"Jeu introuvable: {path}")
    # List top-level contents
    top = _safe_list(ftp, path)
    game["files_sample"] = [e["name"] for e in top[:40]]
    game["entries"] = len(top)
    # Extra sce_sys listing
    sce = _safe_list(ftp, _join(path, "sce_sys"))
    game["sce_sys"] = [e["name"] for e in sce]
    return game


def fetch_icon_bytes(ftp: FTP, icon_path: str) -> bytes:
    if not icon_path:
        raise FileNotFoundError("Pas d’icône")
    data = _ftp_read_bytes(ftp, icon_path, limit=4_000_000)
    if not data:
        raise FileNotFoundError("Icône vide")
    return data


def cache_icon(root: Path, title_id: str, data: bytes, suffix: str = ".png") -> Path:
    cache = root / CACHE_DIR_NAME
    cache.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^A-Z0-9_\-]", "_", (title_id or "GAME").upper())[:32]
    path = cache / f"{safe}{suffix}"
    path.write_bytes(data)
    return path


_scan_lock = threading.Lock()
_scan_cache: Dict[str, Any] = {"host": "", "games": [], "ts": 0.0}
