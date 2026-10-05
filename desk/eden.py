"""ProsperoEden hub — install + game-files under /data/prosperoeden (by Pixam)."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from ftplib import FTP
from pathlib import Path
from typing import Any, Dict, List, Optional

TITLE_ID = "PPSA99008"
# App folder (ZIP → homebrew)
APP_ROOT = f"/data/homebrew/{TITLE_ID}"
# Game files root (keys / firmware / roms) — layout actuel ProsperoEden
DATA_ROOT = "/data/prosperoeden"
KEYS_DIR = f"{DATA_ROOT}/keys"
FIRMWARE_DIR = f"{DATA_ROOT}/firmware"
ROMS_DIR = f"{DATA_ROOT}/roms"
UPDATES_DIR = f"{DATA_ROOT}/updates"
GITHUB_REPO = "blackbearreloaded/ProsperoEden"
GITHUB_API_LATEST = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
GITHUB_API_LIST = f"https://api.github.com/repos/{GITHUB_REPO}/releases"

KIND_DIRS = {
    "keys": KEYS_DIR,
    "firmware": FIRMWARE_DIR,
    "roms": ROMS_DIR,
    "updates": UPDATES_DIR,
}

KIND_EXTS = {
    "keys": {".keys"},
    "firmware": {".nca"},
    "roms": {".nsp", ".xci"},
    "updates": {".nsp", ".xci"},
}


def dest_for_kind(kind: str) -> str:
    k = (kind or "").strip().lower()
    if k not in KIND_DIRS:
        raise ValueError("kind invalide (keys|firmware|roms|updates)")
    return KIND_DIRS[k]


def validate_paths_for_kind(kind: str, paths: List[str]) -> List[str]:
    k = (kind or "").strip().lower()
    exts = KIND_EXTS.get(k)
    if not exts:
        raise ValueError("kind invalide (keys|firmware|roms|updates)")
    out: List[str] = []
    for raw in paths or []:
        p = Path(str(raw))
        if not p.is_file():
            continue
        suf = p.suffix.lower()
        name = p.name.lower()
        if k == "keys":
            if suf in exts or name in ("prod.keys", "title.keys"):
                out.append(str(p.resolve()))
        elif suf in exts:
            out.append(str(p.resolve()))
    if not out:
        raise ValueError(f"Aucun fichier valide pour {kind}")
    return out


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
                "path": f"{path.rstrip('/')}/{name}",
            }
        )
    return entries


def _exists_dir(ftp: FTP, path: str) -> bool:
    try:
        ftp.cwd(path)
        return True
    except Exception:
        return False


def status(ftp: FTP) -> Dict[str, Any]:
    app_installed = _exists_dir(ftp, APP_ROOT)
    data_present = _exists_dir(ftp, DATA_ROOT)
    keys = _safe_list(ftp, KEYS_DIR)
    firmware = _safe_list(ftp, FIRMWARE_DIR)
    roms = _safe_list(ftp, ROMS_DIR)
    key_names = {e["name"].lower() for e in keys if e["type"] == "file"}
    rom_files = [
        {"name": e["name"], "size": e["size"], "path": e["path"]}
        for e in roms
        if e["type"] == "file" and Path(e["name"]).suffix.lower() in (".nsp", ".xci")
    ]
    rom_files.sort(key=lambda r: r["name"].lower())
    fw_files = [e for e in firmware if e["type"] == "file"]
    return {
        "ok": True,
        "title_id": TITLE_ID,
        "app_root": APP_ROOT,
        "data_root": DATA_ROOT,
        "installed": app_installed,
        "data_present": data_present,
        "paths": {
            "app": APP_ROOT,
            "data": DATA_ROOT,
            "keys": KEYS_DIR,
            "firmware": FIRMWARE_DIR,
            "roms": ROMS_DIR,
            "updates": UPDATES_DIR,
        },
        "keys": {
            "prod_keys": "prod.keys" in key_names,
            "title_keys": "title.keys" in key_names,
            "files": [e["name"] for e in keys if e["type"] == "file"],
        },
        "firmware": {
            "count": len(fw_files),
            "bytes": sum(e["size"] for e in fw_files),
        },
        "roms": rom_files,
        "roms_count": len(rom_files),
        "github": f"https://github.com/{GITHUB_REPO}",
    }


def _github_json(url: str) -> Any:
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "PSHomebrewDesk/Pixam",
        },
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def _pick_zip_asset(assets: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(assets, list):
        return None
    zip_asset: Optional[Dict[str, Any]] = None
    for a in assets:
        if not isinstance(a, dict):
            continue
        name = str(a.get("name") or "")
        low = name.lower()
        if low.endswith(".zip") and "source" not in low and "ffpfsc" not in low:
            return a
        if low.endswith(".zip") and zip_asset is None:
            zip_asset = a
    return zip_asset


def latest_release() -> Dict[str, Any]:
    data: Optional[Dict[str, Any]] = None
    try:
        raw = _github_json(GITHUB_API_LATEST)
        if isinstance(raw, dict):
            data = raw
    except urllib.error.HTTPError as exc:
        if exc.code != 404:
            raise RuntimeError(f"GitHub HTTP {exc.code}") from exc
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"Release ProsperoEden indisponible: {exc}") from exc

    if not data:
        try:
            rows = _github_json(GITHUB_API_LIST)
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"Release ProsperoEden indisponible: {exc}") from exc
        if not isinstance(rows, list) or not rows:
            raise RuntimeError("Aucune release ProsperoEden")
        for row in rows:
            if isinstance(row, dict) and not row.get("draft"):
                data = row
                break
        if not data and isinstance(rows[0], dict):
            data = rows[0]

    if not isinstance(data, dict):
        raise RuntimeError("Release ProsperoEden invalide")

    tag = str(data.get("tag_name") or data.get("name") or "")
    zip_asset = _pick_zip_asset(data.get("assets"))
    if not zip_asset:
        raise RuntimeError("Aucun ZIP dans la dernière release ProsperoEden")

    return {
        "ok": True,
        "tag": tag,
        "name": str(data.get("name") or tag),
        "url": str(zip_asset.get("browser_download_url") or ""),
        "filename": str(zip_asset.get("name") or "ProsperoEden.zip"),
        "bytes": int(zip_asset.get("size") or 0),
        "html_url": str(data.get("html_url") or f"https://github.com/{GITHUB_REPO}/releases"),
        "repo": GITHUB_REPO,
    }


def assert_rom_path(path: str) -> str:
    p = (path or "").replace("\\", "/").strip()
    while "//" in p:
        p = p.replace("//", "/")
    allowed_roots = (ROMS_DIR + "/", UPDATES_DIR + "/")
    if not any(p.startswith(root) for root in allowed_roots):
        raise PermissionError("Suppression limitée à /data/prosperoeden/roms (ou updates/)")
    if ".." in p.split("/"):
        raise ValueError("Chemin invalide")
    name = Path(p).name
    if Path(name).suffix.lower() not in (".nsp", ".xci"):
        raise ValueError("Seuls .nsp / .xci peuvent être supprimés ici")
    return p
