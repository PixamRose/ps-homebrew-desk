"""Build / publish LAN update packages for PS Homebrew Desk."""

from __future__ import annotations

import hashlib
import json
import time
import zipfile
from pathlib import Path
from typing import Any, Dict, Iterable, Set

from desk_common import ROOT, UPDATES_DIR, app_version, load_version, local_ip, desk_port

SKIP_DIR_NAMES = {
    ".git",
    ".iconbuild",
    "__pycache__",
    "vendor",
    "updates",
    "node_modules",
    ".venv",
    "venv",
}
SKIP_FILE_SUFFIXES = {".pyc", ".pyo", ".DS_Store"}
INCLUDE_ALWAYS = {
    "app.py",
    "desktop.py",
    "transfer.py",
    "relapse.py",
    "desk_common.py",
    "update_channel.py",
    "version.json",
    "requirements.txt",
    "README.md",
    "start.command",
    "start.bat",
    "start-lan.command",
    "start-lan.bat",
}


def _should_skip(path: Path) -> bool:
    parts = set(path.parts)
    if parts & SKIP_DIR_NAMES:
        return True
    if path.suffix in SKIP_FILE_SUFFIXES:
        return True
    if path.name.startswith("."):
        return True
    return False


def iter_package_files(root: Path = ROOT) -> Iterable[Path]:
    root = root.resolve()
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if _should_skip(rel):
            continue
        # Keep catalog JSON but not huge mirrored binaries by default
        if rel.parts[:1] == ("catalog",) and len(rel.parts) > 2 and rel.parts[1] == "files":
            continue
        yield path


def build_update_zip(notes: str = "") -> Dict[str, Any]:
    UPDATES_DIR.mkdir(parents=True, exist_ok=True)
    version = app_version()
    stamp = time.strftime("%Y%m%d-%H%M%S")
    zip_name = f"pshomebrew-desk-{version}-{stamp}.zip"
    zip_path = UPDATES_DIR / zip_name
    latest = UPDATES_DIR / "latest.zip"

    files = list(iter_package_files())
    if not files:
        raise RuntimeError("Aucun fichier à empaqueter")

    h = hashlib.sha256()
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in files:
            rel = path.relative_to(ROOT).as_posix()
            data = path.read_bytes()
            zf.writestr(rel, data)
            h.update(data)
            h.update(rel.encode("utf-8"))

    latest.write_bytes(zip_path.read_bytes())
    digest = hashlib.sha256(latest.read_bytes()).hexdigest()
    ver = load_version()
    manifest = {
        "ok": True,
        "name": ver.get("name"),
        "version": version,
        "channel": ver.get("channel") or "stable",
        "notes": (notes or ver.get("notes") or "").strip(),
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "sha256": digest,
        "bytes": latest.stat().st_size,
        "file": "latest.zip",
        "url": f"/updates/latest.zip",
        "zip_name": zip_name,
        "file_count": len(files),
        "lan_url": f"http://{local_ip()}:{desk_port()}/updates/latest.zip",
    }
    (UPDATES_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def apply_update_zip(zip_path: Path, target: Path = ROOT) -> Dict[str, Any]:
    """Extract an update zip over the install (keeps vendor/updates)."""
    zip_path = Path(zip_path)
    target = Path(target)
    if not zip_path.is_file():
        raise FileNotFoundError(str(zip_path))
    written: Set[str] = set()
    with zipfile.ZipFile(zip_path, "r") as zf:
        for info in zf.infolist():
            name = info.filename.replace("\\", "/").lstrip("/")
            if not name or name.endswith("/"):
                continue
            parts = Path(name).parts
            if not parts or parts[0] in SKIP_DIR_NAMES or ".." in parts:
                continue
            dest = target / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(zf.read(info))
            written.add(name)
    return {"ok": True, "written": len(written), "version": app_version()}
