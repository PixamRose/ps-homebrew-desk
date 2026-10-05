"""Orbit Store hub — install ELF + status on :34177 (by Pixam)."""

from __future__ import annotations

import hashlib
import json
import socket
import time
import urllib.error
import urllib.request
from ftplib import FTP
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from desk.common import app_root

ORBIT_PORT = 34177
ORBIT_DIR = "/data/orbit-store"
ORBIT_ELF_NAME = "orbit_store.elf"
ORBIT_ELF_PATH = f"{ORBIT_DIR}/{ORBIT_ELF_NAME}"
# Fallback if /data/orbit-store fails on some setups
ORBIT_FALLBACK_DIR = "/data/homebrew"
GITHUB_REPO = "saawant12/orbit-store-ps5"
GITHUB_API_LATEST = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
GITHUB_API_LIST = f"https://api.github.com/repos/{GITHUB_REPO}/releases"
GITHUB_RELEASES = f"https://github.com/{GITHUB_REPO}/releases"

_UA = "PSHomebrewDesk/Pixam"
_CHUNK = 1024 * 256


def probe_port(host: str, port: int = ORBIT_PORT, timeout: float = 1.2) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def cache_dir() -> Path:
    d = app_root() / "cache" / "orbit"
    d.mkdir(parents=True, exist_ok=True)
    return d


def payloads_elf_path(payloads_dir: Path) -> Path:
    return payloads_dir / ORBIT_ELF_NAME


def local_cached_elf(payloads_dir: Path) -> Optional[Path]:
    for path in (payloads_elf_path(payloads_dir), cache_dir() / ORBIT_ELF_NAME):
        if path.is_file() and path.stat().st_size > 1024 and _is_elf(path):
            return path
    return None


def _is_elf(path: Path) -> bool:
    try:
        with path.open("rb") as f:
            return f.read(4) == b"\x7fELF"
    except OSError:
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
                "path": f"{path.rstrip('/')}/{name}",
            }
        )
    return entries


def _find_elf(ftp: FTP) -> Optional[Dict[str, Any]]:
    for folder in (ORBIT_DIR, ORBIT_FALLBACK_DIR, "/data/homebrew/payloads", "/data/homebrew/elfs"):
        for e in _safe_list(ftp, folder):
            if e["type"] == "file" and e["name"].lower() == ORBIT_ELF_NAME:
                return {"path": e["path"], "size": e["size"], "name": e["name"]}
    return None


def status(ftp: FTP, host: str) -> Dict[str, Any]:
    dir_entries = _safe_list(ftp, ORBIT_DIR)
    dir_present = bool(dir_entries) or _cwd_ok(ftp, ORBIT_DIR)
    elf = _find_elf(ftp)
    online = probe_port(host, ORBIT_PORT) if host else False
    url = f"http://{host}:{ORBIT_PORT}/" if host else ""
    return {
        "ok": True,
        "orbit_dir": ORBIT_DIR,
        "elf_name": ORBIT_ELF_NAME,
        "elf_path": ORBIT_ELF_PATH,
        "dir_present": dir_present,
        "installed": bool(elf) or dir_present,
        "elf": elf,
        "port": ORBIT_PORT,
        "online": online,
        "url": url,
        "github": f"https://github.com/{GITHUB_REPO}",
        "releases": GITHUB_RELEASES,
    }


def _cwd_ok(ftp: FTP, path: str) -> bool:
    try:
        ftp.cwd(path)
        return True
    except Exception:
        return False


def _github_json(url: str) -> Any:
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": _UA,
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


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
        raise RuntimeError(f"Release Orbit indisponible: {exc}") from exc

    if not data:
        try:
            rows = _github_json(GITHUB_API_LIST)
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"Release Orbit indisponible: {exc}") from exc
        if not isinstance(rows, list) or not rows:
            raise RuntimeError("Aucune release Orbit")
        for row in rows:
            if isinstance(row, dict) and not row.get("draft"):
                data = row
                break
        if not data and isinstance(rows[0], dict):
            data = rows[0]

    if not isinstance(data, dict):
        raise RuntimeError("Release Orbit invalide")

    tag = str(data.get("tag_name") or data.get("name") or "")
    assets = data.get("assets") if isinstance(data.get("assets"), list) else []
    elf_asset: Optional[Dict[str, Any]] = None
    sha_asset: Optional[Dict[str, Any]] = None
    for a in assets:
        if not isinstance(a, dict):
            continue
        name = str(a.get("name") or "").lower()
        if name == ORBIT_ELF_NAME:
            elf_asset = a
        elif name == f"{ORBIT_ELF_NAME}.sha256" or name.endswith("orbit_store.elf.sha256"):
            sha_asset = a
    if not elf_asset:
        raise RuntimeError("orbit_store.elf introuvable dans la dernière release")

    sha256 = ""
    if sha_asset and sha_asset.get("browser_download_url"):
        try:
            text = _download_text(str(sha_asset["browser_download_url"]), timeout=20)
            sha256 = text.split()[0].lower() if text.strip() else ""
            if len(sha256) != 64:
                sha256 = ""
        except Exception:
            sha256 = ""

    return {
        "ok": True,
        "tag": tag,
        "name": str(data.get("name") or tag),
        "url": str(elf_asset.get("browser_download_url") or ""),
        "filename": ORBIT_ELF_NAME,
        "bytes": int(elf_asset.get("size") or 0),
        "sha256": sha256,
        "html_url": str(data.get("html_url") or GITHUB_RELEASES),
        "repo": GITHUB_REPO,
        "port": ORBIT_PORT,
    }


def _download_text(url: str, timeout: float = 30) -> str:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": _UA, "Accept": "*/*"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def download_elf(
    url: str,
    dest: Path,
    *,
    expected_sha256: str = "",
    expected_bytes: int = 0,
    retries: int = 3,
) -> Path:
    """Download orbit_store.elf to dest with retries + ELF/sha checks."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    last_err: Optional[BaseException] = None
    for attempt in range(1, max(1, retries) + 1):
        partial = dest.with_suffix(dest.suffix + f".part{attempt}")
        try:
            if partial.exists():
                partial.unlink()
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": _UA,
                    "Accept": "application/octet-stream,*/*",
                    "Accept-Encoding": "identity",
                },
            )
            # Long socket timeout: 44MB ELF on slow links
            with urllib.request.urlopen(req, timeout=600) as resp:
                total = int(resp.headers.get("Content-Length") or expected_bytes or 0)
                written = 0
                h = hashlib.sha256()
                with partial.open("wb") as out:
                    while True:
                        chunk = resp.read(_CHUNK)
                        if not chunk:
                            break
                        out.write(chunk)
                        h.update(chunk)
                        written += len(chunk)
            if written < 1024:
                raise RuntimeError(f"Téléchargement trop petit ({written} o)")
            if expected_bytes and written != expected_bytes:
                # GitHub sometimes omits exact match after redirect — warn via size floor
                if abs(written - expected_bytes) > 64:
                    raise RuntimeError(
                        f"Taille incorrecte: {written} o (attendu {expected_bytes})"
                    )
            digest = h.hexdigest()
            if expected_sha256 and digest != expected_sha256.lower():
                raise RuntimeError(f"SHA-256 mismatch: {digest[:16]}…")
            if not _is_elf(partial):
                raise RuntimeError("Fichier téléchargé n’est pas un ELF valide")
            if dest.exists():
                dest.unlink()
            partial.replace(dest)
            return dest
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            try:
                if partial.exists():
                    partial.unlink()
            except OSError:
                pass
            if attempt < retries:
                time.sleep(1.2 * attempt)
                continue
            break
    raise RuntimeError(f"Download Orbit échoué: {last_err}")


def ensure_local_elf(
    payloads_dir: Path,
    *,
    force: bool = False,
    release: Optional[Dict[str, Any]] = None,
) -> Tuple[Path, Dict[str, Any]]:
    """Return local orbit_store.elf path, downloading if needed."""
    rel = release or latest_release()
    url = str(rel.get("url") or "").strip()
    if not url:
        raise RuntimeError("URL orbit_store.elf introuvable")
    expected = int(rel.get("bytes") or 0)
    sha = str(rel.get("sha256") or "").strip().lower()

    # Prefer payloads/ as the durable cache (also used by elfldr)
    targets = [payloads_elf_path(payloads_dir), cache_dir() / ORBIT_ELF_NAME]
    if not force:
        for path in targets:
            if not path.is_file():
                continue
            size = path.stat().st_size
            if size < 1024 or not _is_elf(path):
                continue
            if expected and abs(size - expected) > 64:
                continue
            if sha:
                dig = hashlib.sha256(path.read_bytes()).hexdigest()
                if dig != sha:
                    continue
            return path, rel

    dest = payloads_elf_path(payloads_dir)
    payloads_dir.mkdir(parents=True, exist_ok=True)
    download_elf(url, dest, expected_sha256=sha, expected_bytes=expected, retries=3)
    # Mirror into cache/
    try:
        cache_copy = cache_dir() / ORBIT_ELF_NAME
        if cache_copy != dest:
            cache_copy.write_bytes(dest.read_bytes())
    except OSError:
        pass
    return dest, rel
