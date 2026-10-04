"""Detect & manage .elf payloads on the console (and local payloads/)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
from ftplib import FTP

TITLE_IN_NAME_RE = re.compile(r"([A-Z]{4}\d{5})", re.I)
VERSION_RE = re.compile(
    r"(?:^|[-_.\s])v?(\d+(?:\.\d+){0,3})(?:[-_.]|$)",
    re.I,
)
HASH_SUFFIX_RE = re.compile(r"[-_][0-9a-f]{7,12}$", re.I)
PS5_SUFFIX_RE = re.compile(r"[-_]ps5(?:-install)?$", re.I)

SCAN_ROOTS = (
    "/data/homebrew",
    "/data/homebrew/payloads",
    "/data/homebrew/elfs",
    "/data/ps5_autoloader",
    "/user/homebrew",
    "/homebrew",
    "/mnt/usb0",
    "/mnt/usb1",
    "/usb0",
    "/usb1",
)

PROTECTED_NAMES = frozenset(
    {
        # Keep common bootstrapping payloads uninstall-guarded unless user confirms via UI
    }
)


def family_key(filename: str) -> str:
    stem = Path(filename or "").stem.lower()
    stem = HASH_SUFFIX_RE.sub("", stem)
    stem = PS5_SUFFIX_RE.sub("", stem)
    # drop trailing version-like chunks repeatedly
    for _ in range(3):
        nxt = re.sub(r"[-_]v?\d+(?:\.\d+){0,3}$", "", stem)
        if nxt == stem:
            break
        stem = nxt
    # collapse common multi-part names to first meaningful token(s)
    parts = [p for p in re.split(r"[-_]+", stem) if p and p not in ("elf", "bin")]
    if not parts:
        return stem or "unknown"
    if len(parts) == 1:
        return parts[0]
    # keep compound like crispy-doom
    if parts[0] in ("crispy", "ps5", "payload"):
        return "-".join(parts[:2])
    return parts[0]


def parse_version(text: str) -> str:
    if not text:
        return ""
    m = VERSION_RE.search(text)
    return m.group(1) if m else ""


def version_tuple(ver: str) -> Tuple[int, ...]:
    parts: List[int] = []
    for chunk in re.split(r"[^\d]+", (ver or "").strip()):
        if chunk.isdigit():
            parts.append(int(chunk))
    return tuple(parts) if parts else (0,)


def version_gt(a: str, b: str) -> bool:
    """True if a > b (semver-ish). Empty b loses to any a."""
    if not a:
        return False
    if not b:
        return True
    return version_tuple(a) > version_tuple(b)


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
    parent = (parent or "").rstrip("/") or ""
    if not parent:
        return "/" + name
    return f"{parent}/{name}"


def _source_label(path: str) -> str:
    p = path.replace("\\", "/")
    if p.startswith("local:"):
        return "Mac · payloads/"
    if "/mnt/usb" in p or p.startswith("/usb"):
        return "USB"
    if "/ps5_autoloader" in p:
        return "autoloader"
    if "/homebrew" in p:
        return "homebrew"
    if p.startswith("/data"):
        return "data"
    if p.startswith("/user"):
        return "user"
    return "autre"


def _can_uninstall(path: str) -> bool:
    p = path.replace("\\", "/")
    if p.startswith("local:"):
        return True
    if not p.startswith(("/user/", "/data/", "/mnt/", "/usb", "/homebrew")):
        return False
    if p.rstrip("/") in (
        "/user",
        "/data",
        "/user/homebrew",
        "/data/homebrew",
        "/homebrew",
        "/mnt",
        "/data/ps5_autoloader",
    ):
        return False
    return p.lower().endswith(".elf")


def build_catalog_index(catalog: Dict[str, Any]) -> Dict[str, Any]:
    """Index catalog ELF items by filename and family."""
    by_filename: Dict[str, Dict[str, Any]] = {}
    by_family: Dict[str, List[Dict[str, Any]]] = {}
    for raw in catalog.get("items") or []:
        if raw.get("enabled") is False:
            continue
        filename = str(raw.get("filename") or "").strip()
        if not filename.lower().endswith(".elf"):
            continue
        item = {
            "id": raw.get("id") or "",
            "name": raw.get("name") or filename,
            "summary": raw.get("summary") or "",
            "filename": filename,
            "url": raw.get("url") or "",
            "remote_url": raw.get("remote_url") or "",
            "sha256": raw.get("sha256") or "",
            "source": raw.get("source") or "",
            "version": str(raw.get("version") or parse_version(raw.get("name") or "") or parse_version(filename)),
            "bytes": raw.get("bytes") or 0,
            "firmware": raw.get("firmware") or "",
            "tags": raw.get("tags") or [],
            "family": family_key(filename),
        }
        by_filename[filename.lower()] = item
        by_family.setdefault(item["family"], []).append(item)
    for family, items in by_family.items():
        items.sort(key=lambda i: version_tuple(i.get("version") or ""), reverse=True)
    return {"by_filename": by_filename, "by_family": by_family}


def match_catalog(filename: str, index: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """Return (exact_or_best_match, newest_in_family)."""
    by_fn = index.get("by_filename") or {}
    by_fam = index.get("by_family") or {}
    exact = by_fn.get(filename.lower())
    fam = family_key(filename)
    family_items = by_fam.get(fam) or []
    newest = family_items[0] if family_items else None
    if exact:
        return exact, newest
    # fuzzy: same family, prefer matching stem without hash
    stem = Path(filename).stem.lower()
    stem_clean = HASH_SUFFIX_RE.sub("", stem)
    stem_clean = PS5_SUFFIX_RE.sub("", stem_clean)
    for item in family_items:
        ist = Path(item["filename"]).stem.lower()
        ist_clean = HASH_SUFFIX_RE.sub("", ist)
        ist_clean = PS5_SUFFIX_RE.sub("", ist_clean)
        if ist_clean == stem_clean or ist == stem:
            return item, newest
    return (family_items[0] if family_items else None), newest


def enrich_elf(
    *,
    filename: str,
    path: str,
    size: int,
    index: Dict[str, Any],
    location: str = "console",
) -> Dict[str, Any]:
    match, newest = match_catalog(filename, index)
    installed_ver = ""
    if match:
        installed_ver = match.get("version") or ""
    if not installed_ver:
        installed_ver = parse_version(filename) or parse_version(Path(filename).stem)
    display_name = (match.get("name") if match else None) or Path(filename).stem
    # Prefer short product name
    if match and match.get("filename"):
        display_name = Path(match["filename"]).stem
        # nicer: use catalog name before "·"
        cat_name = str(match.get("name") or "")
        if "·" in cat_name:
            display_name = cat_name.split("·", 1)[0].strip()
        elif " · " in cat_name:
            display_name = cat_name.split(" · ", 1)[0].strip()

    latest_ver = (newest or {}).get("version") or ""
    update_available = bool(
        newest
        and newest.get("url")
        and (
            version_gt(latest_ver, installed_ver)
            or (
                match
                and newest.get("filename", "").lower() != filename.lower()
                and version_tuple(latest_ver) >= version_tuple(installed_ver)
                and newest.get("sha256")
                and match.get("sha256")
                and newest.get("sha256") != match.get("sha256")
            )
        )
    )
    # If exact match is already the newest, no update
    if match and newest and match.get("id") == newest.get("id"):
        update_available = False
    if match and newest and match.get("sha256") and match.get("sha256") == newest.get("sha256"):
        update_available = False

    github = (match or newest or {}).get("source") or ""
    return {
        "filename": filename,
        "path": path,
        "size": size,
        "family": family_key(filename),
        "name": display_name,
        "version": installed_ver or "—",
        "latest_version": latest_ver or installed_ver or "",
        "update_available": update_available,
        "github": github,
        "summary": (match or {}).get("summary") or (newest or {}).get("summary") or "",
        "firmware": (match or {}).get("firmware") or "",
        "source_label": _source_label(path),
        "location": location,
        "can_uninstall": _can_uninstall(path),
        "catalog_id": (match or {}).get("id") or "",
        "update_catalog_id": (newest or {}).get("id") or "",
        "update_filename": (newest or {}).get("filename") or "",
        "update_url": (newest or {}).get("url") or "",
        "update_sha256": (newest or {}).get("sha256") or "",
        "sha256_known": (match or {}).get("sha256") or "",
        "tags": (match or newest or {}).get("tags") or [],
    }


def scan_console_elfs(ftp: FTP, catalog: Dict[str, Any], roots: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    index = build_catalog_index(catalog)
    roots = roots or list(SCAN_ROOTS)
    found: List[Dict[str, Any]] = []
    seen: Set[str] = set()

    def add_file(path: str, name: str, size: int) -> None:
        if not name.lower().endswith(".elf"):
            return
        if path in seen:
            return
        seen.add(path)
        found.append(enrich_elf(filename=name, path=path, size=size, index=index, location="console"))

    deep_roots = {
        "/data/homebrew",
        "/user/homebrew",
        "/homebrew",
        "/mnt/usb0",
        "/mnt/usb1",
        "/usb0",
        "/usb1",
    }

    for root in roots:
        entries = _safe_list(ftp, root)
        if not entries:
            continue
        for entry in entries:
            name = entry["name"]
            path = _join(root, name)
            if entry["type"] == "file":
                add_file(path, name, entry.get("size") or 0)
            elif entry["type"] == "dir" and root.rstrip("/") in deep_roots:
                for child in _safe_list(ftp, path):
                    if child["type"] == "file":
                        add_file(_join(path, child["name"]), child["name"], child.get("size") or 0)

    found.sort(key=lambda e: (not e.get("update_available"), (e.get("name") or "").lower()))
    return found


def scan_local_payloads(payloads_dir: Path, catalog: Dict[str, Any]) -> List[Dict[str, Any]]:
    index = build_catalog_index(catalog)
    payloads_dir.mkdir(parents=True, exist_ok=True)
    found: List[Dict[str, Any]] = []
    for path in sorted(payloads_dir.glob("*.elf")):
        item = enrich_elf(
            filename=path.name,
            path=f"local:{path.name}",
            size=path.stat().st_size,
            index=index,
            location="local",
        )
        item["local_path"] = str(path.resolve())
        found.append(item)
    return found


def scan_all(
    ftp: Optional[FTP],
    catalog: Dict[str, Any],
    payloads_dir: Path,
) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    if ftp is not None:
        items.extend(scan_console_elfs(ftp, catalog))
    items.extend(scan_local_payloads(payloads_dir, catalog))
    # Dedup: prefer console over local for same filename+size? keep both with different paths
    items.sort(
        key=lambda e: (
            0 if e.get("update_available") else 1,
            0 if e.get("location") == "console" else 1,
            (e.get("name") or "").lower(),
        )
    )
    return items
