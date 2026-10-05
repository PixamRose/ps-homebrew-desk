"""Persistent transfer history + console profiles (by Pixam)."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from desk.common import app_root

_lock = threading.Lock()
MAX_HISTORY = 80
DEFAULT_GITHUB = "https://github.com/PixamRose/ps-homebrew-desk"
DEFAULT_DISCORD = "https://discord.gg/rrQd6NKHbg"


def _hist_path() -> Path:
    return app_root() / "cache" / "transfer-history.json"


def _profiles_path() -> Path:
    return app_root() / "cache" / "console-profiles.json"


def _links_path() -> Path:
    return app_root() / "cache" / "community-links.json"


def _prefs_path() -> Path:
    return app_root() / "cache" / "desk-prefs.json"


def _read_json(path: Path, default: Any) -> Any:
    try:
        if path.is_file():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return default


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def append_history(entry: Dict[str, Any]) -> None:
    with _lock:
        items = _read_json(_hist_path(), [])
        if not isinstance(items, list):
            items = []
        row = dict(entry)
        row["saved_at"] = time.time()
        items.insert(0, row)
        _write_json(_hist_path(), items[:MAX_HISTORY])


def list_history(limit: int = 40) -> List[Dict[str, Any]]:
    with _lock:
        items = _read_json(_hist_path(), [])
    if not isinstance(items, list):
        return []
    return items[: max(1, min(200, limit))]


def clear_history() -> None:
    with _lock:
        _write_json(_hist_path(), [])


def list_profiles() -> List[Dict[str, Any]]:
    with _lock:
        data = _read_json(_profiles_path(), {"profiles": []})
    if isinstance(data, dict) and isinstance(data.get("profiles"), list):
        return data["profiles"]
    return []


def save_profiles(profiles: List[Dict[str, Any]], active: str = "") -> Dict[str, Any]:
    cleaned: List[Dict[str, Any]] = []
    for p in profiles or []:
        if not isinstance(p, dict):
            continue
        name = str(p.get("name") or "").strip()
        host = str(p.get("host") or "").strip()
        if not name or not host:
            continue
        cleaned.append(
            {
                "name": name[:48],
                "host": host[:64],
                "companion": bool(p.get("companion")),
                "dest_root": str(p.get("dest_root") or "/data/homebrew")[:128],
                "notes": str(p.get("notes") or "")[:120],
            }
        )
    payload = {"profiles": cleaned, "active": (active or "")[:48]}
    with _lock:
        _write_json(_profiles_path(), payload)
    return payload


def get_profiles_bundle() -> Dict[str, Any]:
    with _lock:
        data = _read_json(_profiles_path(), {"profiles": [], "active": ""})
    if not isinstance(data, dict):
        return {"profiles": [], "active": ""}
    return {
        "profiles": data.get("profiles") if isinstance(data.get("profiles"), list) else [],
        "active": str(data.get("active") or ""),
    }


def get_community_links() -> Dict[str, str]:
    with _lock:
        data = _read_json(
            _links_path(),
            {
                "tiktok": "",
                "github": DEFAULT_GITHUB,
                "discord": DEFAULT_DISCORD,
            },
        )
    if not isinstance(data, dict):
        data = {}
    return {
        "tiktok": str(data.get("tiktok") or ""),
        "github": str(data.get("github") or DEFAULT_GITHUB),
        "discord": str(data.get("discord") or DEFAULT_DISCORD),
    }


def save_community_links(tiktok: str = "", github: str = "", discord: str = "") -> Dict[str, str]:
    payload = {
        "tiktok": (tiktok or "").strip()[:200],
        "github": (github or DEFAULT_GITHUB).strip()[:200],
        "discord": (discord or DEFAULT_DISCORD).strip()[:200],
    }
    with _lock:
        _write_json(_links_path(), payload)
    return payload


_ALLOWED_THEMES = frozenset({"pixam", "dark", "cyberpunk", "midnight", "light"})


def get_prefs() -> Dict[str, Any]:
    with _lock:
        data = _read_json(_prefs_path(), {})
    if not isinstance(data, dict):
        return {}
    return _sanitize_prefs(data)


def save_prefs(prefs: Optional[Dict[str, Any]] = None, *, merge: bool = True) -> Dict[str, Any]:
    incoming = prefs if isinstance(prefs, dict) else {}
    with _lock:
        current = _read_json(_prefs_path(), {})
        if not isinstance(current, dict):
            current = {}
        next_prefs = {**current, **incoming} if merge else dict(incoming)
        cleaned = _sanitize_prefs(next_prefs)
        _write_json(_prefs_path(), cleaned)
    return cleaned


def clear_prefs() -> Dict[str, Any]:
    with _lock:
        _write_json(_prefs_path(), {})
    return {}


def _sanitize_prefs(data: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    host = str(data.get("host") or "").strip()[:64]
    if host:
        out["host"] = host
    ui = str(data.get("uiMode") or "").strip().lower()
    if ui in ("beginner", "advanced"):
        out["uiMode"] = ui
    theme = str(data.get("theme") or "").strip().lower()
    if theme == "light":
        theme = "pixam"
    if theme in _ALLOWED_THEMES:
        out["theme"] = theme
    dest = str(data.get("xferDest") or "").strip()[:256]
    if dest and ".." not in dest.split("/"):
        out["xferDest"] = dest
    custom = str(data.get("xferCustom") or "").strip()[:256]
    if custom:
        out["xferCustom"] = custom
    try:
        workers = int(data.get("workers"))
        out["workers"] = max(1, min(6, workers))
    except (TypeError, ValueError):
        pass
    if "autoConnect" in data:
        out["autoConnect"] = bool(data.get("autoConnect"))
    return out
