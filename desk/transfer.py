"""High-speed parallel FTP transfers into /data/homebrew."""

from __future__ import annotations

import mmap
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import uuid
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from ftplib import FTP, error_perm
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import unquote, urlparse

ARCHIVE_SUFFIXES = {".rar", ".zip", ".7z"}

HOMEBREW_ROOT = "/data/homebrew"
FTP_PORT = 1337
# Large blocks + socket buffers — saturate Wi‑Fi / gigabit when the link allows
BLOCKSIZE = 16 * 1024 * 1024  # 16 MiB
SOCK_BUF = 16 * 1024 * 1024
DEFAULT_WORKERS = 3
MAX_WORKERS = 6
# Global FTP gate — keep a few parallel STOR for multi-file; single huge file uses 1
try:
    _FTP_UPLOAD_SLOTS = max(1, min(6, int(os.environ.get("DESK_FTP_SLOTS", "3"))))
except ValueError:
    _FTP_UPLOAD_SLOTS = 3
SAFE_WRITE_ROOTS = ("/data", "/user", "/mnt", "/usb", "/homebrew")
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

_jobs: Dict[str, "TransferJob"] = {}
_jobs_lock = threading.Lock()
_ftp_upload_sema = threading.BoundedSemaphore(_FTP_UPLOAD_SLOTS)
_ftp_waiters = 0
_ftp_waiters_lock = threading.Lock()


def _safe_remote(path: str) -> str:
    path = (path or "").replace("\\", "/").strip() or HOMEBREW_ROOT
    while "//" in path:
        path = path.replace("//", "/")
    if not path.startswith("/"):
        path = "/" + path.lstrip("/")
    parts = [p for p in path.split("/") if p and p != "."]
    if ".." in parts:
        raise ValueError("Chemin invalide (..)")
    normalized = "/" + "/".join(parts) if parts else "/"
    for blocked in BLOCKED_WRITE_PREFIXES:
        if normalized == blocked or normalized.startswith(blocked + "/"):
            raise ValueError(f"Écriture bloquée: {normalized}")
    if not any(normalized == root or normalized.startswith(root + "/") for root in SAFE_WRITE_ROOTS):
        raise ValueError("Destination hors zones autorisées (/data, /user, /mnt, /usb, /homebrew)")
    return normalized


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


def _tune_sock(sock: socket.socket) -> None:
    """Push TCP buffers / low-latency flags for bulk FTP data."""
    if not sock:
        return
    try:
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    except OSError:
        pass
    for opt in (socket.SO_SNDBUF, socket.SO_RCVBUF):
        try:
            sock.setsockopt(socket.SOL_SOCKET, opt, SOCK_BUF)
        except OSError:
            pass


class FastFTP(FTP):
    """ftplib FTP with tuned data-connection sockets."""

    def connect(self, host="", port=0, timeout=-999, source_address=None):
        r = super().connect(host, port, timeout, source_address)
        if self.sock:
            _tune_sock(self.sock)
        return r

    def ntransfercmd(self, cmd, rest=None):
        conn, size = super().ntransfercmd(cmd, rest)
        if conn is not None:
            _tune_sock(conn)
        return conn, size


def ftp_connect(host: str, timeout: float = 120.0) -> FTP:
    ftp = FastFTP()
    # Long timeout for multi‑GiB STOR
    ftp.connect(host, FTP_PORT, timeout=timeout)
    ftp.login()
    ftp.set_pasv(True)
    try:
        ftp.voidcmd("TYPE I")
    except Exception:
        pass
    if ftp.sock:
        _tune_sock(ftp.sock)
        try:
            ftp.sock.settimeout(timeout)
        except OSError:
            pass
    return ftp


def _acquire_ftp_slot(should_cancel: Optional[Callable[[], bool]] = None) -> None:
    global _ftp_waiters
    with _ftp_waiters_lock:
        _ftp_waiters += 1
    got = False
    try:
        while True:
            if should_cancel and should_cancel():
                raise TransferCancelled("Annulé en file FTP")
            if _ftp_upload_sema.acquire(timeout=0.4):
                got = True
                break
    finally:
        with _ftp_waiters_lock:
            _ftp_waiters = max(0, _ftp_waiters - 1)
    if not got:
        raise TransferCancelled("Annulé en file FTP")


def upload_file(
    host: str,
    local_path: Path,
    remote_path: str,
    on_bytes: Optional[Callable[[int], None]] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
    resume: bool = True,
) -> int:
    """High-speed local file → FTP using mmap + raw data-socket sendall.

    If resume=True and the remote partial file exists (SIZE), try REST + STOR.
    """
    remote_path = _safe_remote(remote_path)
    parent = remote_path.rsplit("/", 1)[0]
    sent = 0
    file_size = local_path.stat().st_size

    _acquire_ftp_slot(should_cancel)
    ftp = None
    data = None
    try:
        ftp = ftp_connect(host)
        ensure_remote_dir(ftp, parent)
        if file_size == 0:
            ftp.storbinary(f"STOR {remote_path}", local_path.open("rb"), blocksize=BLOCKSIZE)
            return 0
        pos = 0
        if resume:
            try:
                remote_size = ftp.size(remote_path)
            except Exception:
                remote_size = None
            if isinstance(remote_size, int) and 0 < remote_size < file_size:
                try:
                    ftp.sendcmd(f"REST {remote_size}")
                    pos = remote_size
                    sent = remote_size
                except Exception:
                    pos = 0
                    sent = 0
        data = ftp.transfercmd(f"STOR {remote_path}")
        _tune_sock(data)
        try:
            data.settimeout(120.0)
        except OSError:
            pass
        with local_path.open("rb") as raw:
            try:
                mm = mmap.mmap(raw.fileno(), 0, access=mmap.ACCESS_READ)
            except (OSError, ValueError):
                # Some Windows files / FS don't support mmap — buffered fallback.
                mm = None
            try:
                while pos < file_size:
                    if should_cancel and should_cancel():
                        raise TransferCancelled("Annulé par l’utilisateur")
                    end = min(file_size, pos + BLOCKSIZE)
                    if mm is not None:
                        view = mm[pos:end]
                    else:
                        raw.seek(pos)
                        view = raw.read(end - pos)
                    offset = 0
                    while offset < len(view):
                        n = data.send(view[offset : offset + min(4 * 1024 * 1024, len(view) - offset)])
                        if n <= 0:
                            raise RuntimeError("FTP data connection fermée")
                        offset += n
                        sent += n
                        if on_bytes:
                            on_bytes(n)
                    pos = end
            finally:
                if mm is not None:
                    mm.close()
        data.close()
        data = None
        ftp.voidresp()
    except TransferCancelled:
        try:
            if data:
                data.close()
        except Exception:
            pass
        try:
            if ftp:
                ftp.abort()
        except Exception:
            pass
        raise
    finally:
        try:
            if data:
                data.close()
        except Exception:
            pass
        try:
            if ftp:
                ftp.close()
        except Exception:
            pass
        _ftp_upload_sema.release()
    return sent


def upload_stream(
    host: str,
    remote_path: str,
    read_chunk: Callable[[int], bytes],
    total_size: int = 0,
    on_bytes: Optional[Callable[[int], None]] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
) -> int:
    """Stream bytes straight into FTP STOR (no full temp spool)."""
    remote_path = _safe_remote(remote_path)
    parent = remote_path.rsplit("/", 1)[0]
    sent = 0

    _acquire_ftp_slot(should_cancel)

    ftp = None
    data = None
    try:
        ftp = ftp_connect(host)
        ensure_remote_dir(ftp, parent)
        data = ftp.transfercmd(f"STOR {remote_path}")
        _tune_sock(data)
        try:
            data.settimeout(120.0)
        except OSError:
            pass
        while True:
            if should_cancel and should_cancel():
                raise TransferCancelled("Annulé par l’utilisateur")
            chunk = read_chunk(BLOCKSIZE)
            if not chunk:
                break
            offset = 0
            while offset < len(chunk):
                n = data.send(chunk[offset : offset + min(4 * 1024 * 1024, len(chunk) - offset)])
                if n <= 0:
                    raise RuntimeError("FTP data connection fermée")
                offset += n
                sent += n
                if on_bytes:
                    on_bytes(n)
            if total_size and sent >= total_size:
                break
        data.close()
        data = None
        ftp.voidresp()
    except TransferCancelled:
        try:
            if data:
                data.close()
        except Exception:
            pass
        try:
            if ftp:
                ftp.abort()
        except Exception:
            pass
        raise
    finally:
        try:
            if data:
                data.close()
        except Exception:
            pass
        try:
            if ftp:
                ftp.close()
        except Exception:
            pass
        _ftp_upload_sema.release()
    return sent


def ftp_queue_status() -> Dict[str, int]:
    with _ftp_waiters_lock:
        waiting = _ftp_waiters
    # Approximate in-flight = slots - available; BoundedSemaphore has _value
    try:
        available = int(getattr(_ftp_upload_sema, "_value", 0))
    except Exception:
        available = 0
    active = max(0, _FTP_UPLOAD_SLOTS - available)
    return {"slots": _FTP_UPLOAD_SLOTS, "active": active, "waiting": waiting}


def collect_local_items(paths: List[str], dest_root: str = HOMEBREW_ROOT) -> List[Tuple[Path, str]]:
    dest_root = _safe_remote(dest_root)
    items: List[Tuple[Path, str]] = []
    for raw in paths:
        root = Path(raw).expanduser().resolve()
        if not root.exists():
            raise FileNotFoundError(str(root))
        if root.is_file():
            items.append((root, _remote_for_filename(dest_root, root.name)))
            continue
        # folder: preserve structure under dest_root/<foldername>/
        base_name = root.name
        for file_path in root.rglob("*"):
            if not file_path.is_file():
                continue
            rel = file_path.relative_to(root).as_posix()
            remote = f"{dest_root}/{base_name}/{rel}"
            items.append((file_path, _safe_remote(remote)))
    return items


class TransferCancelled(Exception):
    """Raised when a running transfer/download is cancelled by the user."""


@dataclass
class TransferJob:
    id: str
    host: str
    total_files: int = 0
    done_files: int = 0
    total_bytes: int = 0
    sent_bytes: int = 0
    status: str = "queued"
    current: str = ""
    errors: List[str] = field(default_factory=list)
    started_at: float = 0.0
    finished_at: float = 0.0
    workers: int = DEFAULT_WORKERS
    kind: str = "transfer"
    remote_path: str = ""
    cancel_requested: bool = False
    pause_requested: bool = False
    cleaned: bool = False
    # UI phases: queued | download | extract | upload | done | error | cancelled | paused
    phase: str = "queued"
    download_bytes: int = 0
    download_total: int = 0
    upload_bytes: int = 0
    upload_total: int = 0
    extract_bytes: int = 0
    extract_total: int = 0
    # For retry / history
    source_paths: List[str] = field(default_factory=list)
    dest_root: str = HOMEBREW_ROOT
    source_url: str = ""
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def snapshot(self) -> dict:
        with self._lock:
            elapsed = max(0.001, (self.finished_at or time.time()) - (self.started_at or time.time()))
            mbps = (self.sent_bytes * 8) / elapsed / 1_000_000
            dl_pct = (
                round((self.download_bytes / self.download_total) * 100, 1)
                if self.download_total
                else (100.0 if self.phase not in ("queued", "download") and self.kind == "url" else 0.0)
            )
            up_pct = (
                round((self.upload_bytes / self.upload_total) * 100, 1) if self.upload_total else 0.0
            )
            ex_pct = (
                round(min(99.0, (self.extract_bytes / self.extract_total) * 100), 1)
                if self.extract_total
                else 0.0
            )
            # ETA from current phase progress (bytes/sec since job start)
            if self.phase == "download" and self.download_total:
                eta_done, eta_total = self.download_bytes, self.download_total
            elif self.phase == "extract" and self.extract_total:
                eta_done, eta_total = self.extract_bytes, self.extract_total
            elif self.upload_total:
                eta_done, eta_total = self.upload_bytes, self.upload_total
            else:
                eta_done, eta_total = self.sent_bytes, self.total_bytes
            eta_seconds = None
            if (
                self.status not in ("done", "done_with_errors", "error", "cancelled")
                and eta_total > 0
                and eta_done > 0
                and eta_done < eta_total
            ):
                rate = eta_done / elapsed
                if rate > 0:
                    eta_seconds = round((eta_total - eta_done) / rate, 1)
            return {
                "id": self.id,
                "host": self.host,
                "status": self.status,
                "kind": self.kind,
                "phase": self.phase,
                "total_files": self.total_files,
                "done_files": self.done_files,
                "total_bytes": self.total_bytes,
                "sent_bytes": self.sent_bytes,
                "download_bytes": self.download_bytes,
                "download_total": self.download_total,
                "download_percent": dl_pct,
                "upload_bytes": self.upload_bytes,
                "upload_total": self.upload_total,
                "upload_percent": up_pct,
                "extract_bytes": self.extract_bytes,
                "extract_total": self.extract_total,
                "extract_percent": ex_pct,
                "current": self.current,
                "remote_path": self.remote_path,
                "cancel_requested": self.cancel_requested,
                "pause_requested": self.pause_requested,
                "errors": list(self.errors),
                "workers": self.workers,
                "mbps": round(mbps, 2),
                "percent": round((self.sent_bytes / self.total_bytes) * 100, 1) if self.total_bytes else 0.0,
                "started_at": self.started_at,
                "finished_at": self.finished_at,
                "eta_seconds": eta_seconds,
                "source_paths": list(self.source_paths),
                "dest_root": self.dest_root,
                "source_url": self.source_url,
            }


def get_job(job_id: str) -> Optional[TransferJob]:
    with _jobs_lock:
        return _jobs.get(job_id)


def list_jobs(limit: int = 40) -> List[dict]:
    """Recent / active transfer jobs (newest first)."""
    with _jobs_lock:
        jobs = list(_jobs.values())
    jobs.sort(key=lambda j: j.started_at or 0.0, reverse=True)
    out: List[dict] = []
    for job in jobs[: max(1, min(200, limit))]:
        try:
            out.append(job.snapshot())
        except Exception:
            continue
    return out


def _companion_notify(job: "TransferJob", *, force: bool = False) -> None:
    try:
        from desk import companion as companion_mod

        companion_mod.notify_job_obj(job, force=force)
    except Exception:
        pass


def job_is_cancelled(job: TransferJob) -> bool:
    with job._lock:
        return bool(job.cancel_requested)


def job_wait_if_paused(job: TransferJob) -> None:
    """Block upload progress while pause_requested (cooperative pause)."""
    while True:
        with job._lock:
            if job.cancel_requested:
                return
            if not job.pause_requested:
                if job.status == "paused":
                    job.status = "running"
                    if job.phase == "paused":
                        job.phase = "upload"
                return
            job.status = "paused"
            job.phase = "paused"
            job.current = "en pause…"
        time.sleep(0.25)


def cancel_job(job_id: str) -> Optional[TransferJob]:
    job = get_job(job_id)
    if not job:
        return None
    with job._lock:
        if job.status in ("done", "done_with_errors", "error", "cancelled"):
            return job
        job.cancel_requested = True
        job.pause_requested = False
        if job.status in ("queued", "running", "cancelling", "paused"):
            job.status = "cancelling"
            job.current = "annulation…"
    return job


def pause_job(job_id: str) -> Optional[TransferJob]:
    job = get_job(job_id)
    if not job:
        return None
    with job._lock:
        if job.status not in ("queued", "running", "paused", "cancelling"):
            return job
        if job.status == "cancelling":
            return job
        job.pause_requested = True
        job.status = "paused"
        job.phase = "paused"
        job.current = "en pause…"
    _companion_notify(job, force=True)
    return job


def resume_job(job_id: str) -> Optional[TransferJob]:
    job = get_job(job_id)
    if not job:
        return None
    with job._lock:
        if not job.pause_requested and job.status != "paused":
            return job
        job.pause_requested = False
        if job.status == "paused":
            job.status = "running"
            job.phase = "upload"
            job.current = "reprise…"
    _companion_notify(job, force=True)
    return job


def _finish_job_side_effects(job: TransferJob) -> None:
    """History + desktop notification when a job ends."""
    try:
        snap = job.snapshot()
    except Exception:
        return
    try:
        from desk import history as history_mod

        history_mod.append_history(snap)
    except Exception:
        pass
    status = str(snap.get("status") or "")
    if status in ("done", "done_with_errors", "error", "cancelled"):
        try:
            from desk.common import desktop_notify

            name = snap.get("current") or snap.get("remote_path") or snap.get("id") or "transfert"
            if status.startswith("done"):
                desktop_notify("PS Homebrew Desk", f"Terminé · {name}")
            elif status == "cancelled":
                desktop_notify("PS Homebrew Desk", f"Annulé · {name}")
            else:
                desktop_notify("PS Homebrew Desk", f"Erreur · {name}")
        except Exception:
            pass


def ftp_delete_quiet(host: str, remote_path: str) -> bool:
    """Best-effort delete of a (possibly partial) remote file."""
    if not remote_path:
        return False
    try:
        remote_path = _safe_remote(remote_path)
    except Exception:
        return False
    try:
        with ftp_connect(host, timeout=20.0) as ftp:
            try:
                ftp.delete(remote_path)
                return True
            except error_perm:
                # Some firmwares want the bare name after CWD
                parent, _, name = remote_path.rpartition("/")
                if parent:
                    try:
                        ftp.cwd(parent)
                        ftp.delete(name)
                        return True
                    except Exception:
                        return False
                return False
    except Exception:
        return False


def start_transfer(host: str, paths: List[str], dest_root: str = HOMEBREW_ROOT, workers: int = DEFAULT_WORKERS) -> TransferJob:
    items = collect_local_items(paths, dest_root=dest_root)
    if not items:
        raise ValueError("Aucun fichier à transférer")
    workers = max(1, min(MAX_WORKERS, int(workers or DEFAULT_WORKERS)))
    job = TransferJob(id=uuid.uuid4().hex[:12], host=host, workers=workers)
    job.total_files = len(items)
    job.total_bytes = sum(p.stat().st_size for p, _ in items)
    job.source_paths = [str(p) for p in paths]
    job.dest_root = dest_root
    with _jobs_lock:
        _jobs[job.id] = job

    thread = threading.Thread(target=_run_job, args=(job, items), daemon=True)
    thread.start()
    return job


def start_transfer_pairs(host: str, pairs: List[Tuple[Path, str]], workers: int = DEFAULT_WORKERS) -> TransferJob:
    if not pairs:
        raise ValueError("Aucun fichier à transférer")
    workers = max(1, min(MAX_WORKERS, int(workers or DEFAULT_WORKERS)))
    job = TransferJob(id=uuid.uuid4().hex[:12], host=host, workers=workers)
    job.total_files = len(pairs)
    job.total_bytes = sum(p.stat().st_size for p, _ in pairs)
    with _jobs_lock:
        _jobs[job.id] = job
    threading.Thread(target=_run_job, args=(job, pairs), daemon=True).start()
    return job


def _filename_from_url(url: str, explicit: str = "") -> str:
    if explicit:
        return Path(explicit).name
    path = unquote(urlparse(url).path)
    name = Path(path).name
    return name or f"download-{uuid.uuid4().hex[:8]}.bin"


def is_archive_filename(filename: str) -> bool:
    return Path(filename or "").suffix.lower() in ARCHIVE_SUFFIXES


def _remote_for_filename(dest_root: str, filename: str) -> str:
    """Map a local filename to a remote FTP path under dest_root.

    PKG/FPKG → /data/homebrew/pkgs/ only when dest is homebrew root (or already …/pkgs).
    """
    dest_root = _safe_remote(dest_root)
    name = Path(filename or "file.bin").name
    lower = name.lower()
    root = dest_root.rstrip("/")
    if lower.endswith((".pkg", ".fpkg")):
        if root == HOMEBREW_ROOT.rstrip("/"):
            return _safe_remote(f"{HOMEBREW_ROOT}/pkgs/{name}")
        if root.endswith("/pkgs"):
            return _safe_remote(f"{root}/{name}")
    return _safe_remote(f"{root}/{name}")


def _keka_macos_dir() -> Optional[Path]:
    for candidate in (
        Path("/Applications/Keka.app/Contents/MacOS"),
        Path.home() / "Applications/Keka.app/Contents/MacOS",
    ):
        if candidate.is_dir():
            return candidate
    return None


def _is_keka_bundled_tool(path: str) -> bool:
    p = path.replace("\\", "/")
    return "/Keka.app/Contents/MacOS/" in p


def _which_tools() -> List[Tuple[str, str]]:
    """Return extract tools. Prefer Homebrew/system CLIs — Keka.app binaries often crash (exit -5)."""
    found: List[Tuple[str, str]] = []
    seen = set()

    def add(kind: str, path: str) -> None:
        if path and path not in seen and Path(path).is_file():
            found.append((kind, path))
            seen.add(path)

    # 1) System / Homebrew first
    for mac in (
        "/opt/homebrew/bin/unar",
        "/usr/local/bin/unar",
        "/opt/homebrew/bin/unrar",
        "/usr/local/bin/unrar",
        "/opt/homebrew/bin/7z",
        "/usr/local/bin/7z",
        "/opt/homebrew/bin/7zz",
        "/usr/local/bin/7zz",
    ):
        p = Path(mac)
        if p.is_file():
            add(p.stem, str(p))

    for name in ("unar", "unrar", "bsdtar", "tar", "7z", "7zz", "keka"):
        path = shutil.which(name)
        if path:
            kind = "keka-cli" if name == "keka" else name
            add(kind, path)

    for win in (
        r"C:\Program Files\WinRAR\UnRAR.exe",
        r"C:\Program Files (x86)\WinRAR\UnRAR.exe",
        r"C:\Program Files\7-Zip\7z.exe",
        r"C:\Program Files (x86)\7-Zip\7z.exe",
        str(Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "7-Zip" / "7z.exe"),
        str(Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "7-Zip" / "7z.exe"),
    ):
        p = Path(win)
        if p.is_file():
            key = "unrar" if "UnRAR" in p.name else "7z"
            add(key, str(p))

    # 2) Keka.app bundled helpers last (often SIGTRAP / exit -5 on recent macOS)
    keka_dir = _keka_macos_dir()
    if keka_dir:
        add("unar", str(keka_dir / "kekaunar"))
        add("unrar", str(keka_dir / "kekaunrar"))
        add("7zz", str(keka_dir / "keka7zz"))
        add("7z", str(keka_dir / "keka7z"))
    return found


def _extract_wait_seconds(archive: Path) -> int:
    """Scale wait for large game archives (multi‑GiB RAR)."""
    try:
        size_mb = max(1, archive.stat().st_size // (1024 * 1024))
    except OSError:
        size_mb = 100
    # ~3s/MiB soft lower bound for wait polling, min 3 min, max 90 min
    return int(min(90 * 60, max(180, size_mb * 3)))


def list_extract_tools() -> Dict[str, Any]:
    """Report available extractors for Desk UI / diagnostics."""
    tools = _which_tools()
    stable = [
        {"name": n, "path": t, "bundled_keka": _is_keka_bundled_tool(t)}
        for n, t in tools
        if not _is_keka_bundled_tool(t)
    ]
    has_unar = any(x["name"] == "unar" for x in stable)
    has_unrar = any(x["name"] == "unrar" for x in stable)
    has_7z = any(x["name"] in ("7z", "7zz") for x in stable)
    hint = ""
    if sys.platform == "win32":
        if not has_unrar and not has_7z:
            hint = "Windows: installe 7-Zip ou WinRAR pour extraire ZIP/RAR/7z"
        elif not has_7z and not has_unar:
            hint = "7-Zip recommandé pour ZIP/7z (Program Files\\7-Zip\\7z.exe)"
    elif not has_unar and not has_unrar:
        hint = "Installe unar pour des gros RAR fiables : brew install unar"
    elif not has_unar:
        hint = "unar recommandé (plus stable que Keka CLI) : brew install unar"
    return {
        "tools": stable[:12],
        "has_unar": has_unar,
        "has_unrar": has_unrar,
        "hint": hint,
        "ftp_queue": ftp_queue_status(),
    }


def _dir_extracted_bytes(root: Path, exclude: Optional[Path] = None) -> Tuple[int, int]:
    """Return (total_bytes, file_count) under root, skipping exclude and junk."""
    total = 0
    count = 0
    excl = exclude.resolve() if exclude else None
    try:
        for p in root.rglob("*"):
            if (
                not p.is_file()
                or p.name.startswith("._")
                or p.name.startswith(".pshd-")
                or p.name == ".DS_Store"
            ):
                continue
            try:
                if excl and p.resolve() == excl:
                    continue
                total += p.stat().st_size
                count += 1
            except OSError:
                continue
    except OSError:
        pass
    return total, count


def _stage_archive_for_keka(archive: Path, dest_dir: Path) -> Tuple[Path, str]:
    """Place archive into dest_dir without copying multi‑GiB blobs.

    Returns (staged_path, mode) where mode is link|same|inplace.
    Never copies large archives (would double disk + waste minutes).
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    staged = dest_dir / archive.name
    if staged.resolve() == archive.resolve():
        return staged, "same"
    try:
        os.link(archive, staged)
        return staged, "link"
    except OSError:
        pass
    # Extract beside the original temp download instead of copying 3+ GiB
    return archive, "inplace"


def _extract_with_keka_applescript(
    archive: Path,
    dest_dir: Path,
    on_progress: Optional[Any] = None,
) -> None:
    """Use Keka's AppleScript 'extract' (needs Automation permission for Desk/Python)."""
    import json

    dest_dir.mkdir(parents=True, exist_ok=True)
    staged, mode = _stage_archive_for_keka(archive, dest_dir)
    watch_dir = dest_dir if mode != "inplace" else staged.parent

    script = (
        'tell application "Keka"\n'
        "  activate\n"
        f"  extract POSIX file {json.dumps(str(staged))}\n"
        "end tell"
    )
    wait_s = _extract_wait_seconds(archive)
    try:
        proc = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=min(120, wait_s),
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            "Keka ne répond pas (timeout). Vérifie Réglages → Confidentialité → Automatisation "
            "(autoriser Python/Desk à contrôler Keka)."
        ) from exc
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip() or f"exit {proc.returncode}"
        if "not allowed" in err.lower() or "1002" in err or "assistive" in err.lower():
            raise RuntimeError(
                "Permission Automatisation refusée pour Keka. "
                "Réglages Système → Confidentialité et sécurité → Automatisation."
            )
        raise RuntimeError(f"Keka AppleScript: {err[:300]}")

    try:
        archive_size = max(1, archive.stat().st_size)
    except OSError:
        archive_size = 1
    # Don't stop at the first tiny file (e.g. contentids.json 0B) — wait for real payload
    min_bytes = min(archive_size // 2, max(32 * 1024 * 1024, int(archive_size * 0.15)))
    if archive_size < 8 * 1024 * 1024:
        min_bytes = max(1, archive_size // 10)

    deadline = time.time() + wait_s
    stable_since = 0.0
    last_total = -1
    last_count = -1
    started = time.time()
    while time.time() < deadline:
        total, count = _dir_extracted_bytes(watch_dir, exclude=staged)
        if on_progress:
            try:
                on_progress(total, archive_size, count, time.time() - started)
            except Exception:
                pass
        if total == last_total and count == last_count and total > 0:
            if stable_since <= 0:
                stable_since = time.time()
            stable_for = time.time() - stable_since
            need_stable = 12.0 if archive_size > 512 * 1024 * 1024 else 4.0
            if stable_for >= need_stable and total >= min_bytes:
                break
        else:
            stable_since = 0.0
            last_total = total
            last_count = count
        time.sleep(0.7)

    # Move inplace extracts into dest_dir
    if mode == "inplace":
        for p in list(watch_dir.iterdir()):
            if p.resolve() == staged.resolve():
                continue
            if p.name.startswith("."):
                continue
            target = dest_dir / p.name
            if target.exists():
                continue
            try:
                shutil.move(str(p), str(target))
            except OSError:
                try:
                    if p.is_dir():
                        shutil.copytree(p, target)
                    else:
                        shutil.copy2(p, target)
                except OSError:
                    pass

    if mode == "link" and staged.exists():
        try:
            staged.unlink()
        except OSError:
            pass

    total, count = _dir_extracted_bytes(dest_dir, exclude=None)
    if count == 0:
        raise RuntimeError(
            "Keka n’a rien extrait (délai dépassé ou mauvais dossier de sortie). "
            "Dans Keka → Réglages → Extraction : « même dossier que l’archive ». "
            "Ou extrais manuellement le fichier sauvé dans Téléchargements/PSHD-archives."
        )
    if total < min_bytes:
        raise RuntimeError(
            f"Extraction incomplète via Keka ({_fmt_bytes(total)} extraits pour "
            f"une archive de {_fmt_bytes(archive_size)}). Souvent trop tôt, ou RAR multi-parties. "
            "Extrais à la main dans Keka puis envoie le dossier via Transfert."
        )
    if on_progress:
        try:
            on_progress(total, archive_size, count, time.time() - started)
        except Exception:
            pass


def _looks_like_password_error(text: str) -> bool:
    t = (text or "").lower()
    return any(
        key in t
        for key in (
            "password",
            "mot de passe",
            "encrypted",
            "wrong password",
            "incorrect password",
            "bad password",
            "checksum error",  # unrar often reports this for bad pwd
        )
    )


def extract_archive(
    archive: Path,
    dest_dir: Path,
    password: str = "",
    on_progress: Optional[Any] = None,
) -> None:
    """Extract archive on the companion machine (never on the PS5)."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    suffix = archive.suffix.lower()
    pwd = (password or "").strip()
    try:
        archive_size = max(1, archive.stat().st_size)
    except OSError:
        archive_size = 1

    def _emit(done: int, total: int = archive_size, files: int = 0, elapsed: float = 0.0) -> None:
        if not on_progress:
            return
        try:
            on_progress(done, total, files, elapsed)
        except Exception:
            pass

    if suffix == ".zip":
        try:
            with zipfile.ZipFile(archive, "r") as zf:
                dest_root = dest_dir.resolve()
                for info in zf.infolist():
                    name = info.filename.replace("\\", "/")
                    if not name or name.endswith("/"):
                        continue
                    # Block zip-slip (absolute / parent paths)
                    if name.startswith("/") or name.startswith("../") or "/../" in f"/{name}/":
                        raise RuntimeError(f"ZIP dangereux refusé: {name}")
                    target = (dest_dir / name).resolve()
                    if not str(target).startswith(str(dest_root) + "/") and target != dest_root:
                        raise RuntimeError(f"ZIP dangereux refusé: {name}")
                zf.extractall(dest_dir, pwd=pwd.encode("utf-8") if pwd else None)
            done, n = _dir_extracted_bytes(dest_dir)
            _emit(done, archive_size, n, 0)
            return
        except RuntimeError as exc:
            if _looks_like_password_error(str(exc)) or "password" in str(exc).lower():
                raise RuntimeError(
                    "ZIP protégé — renseigne le mot de passe archive dans l’onglet Lien."
                ) from exc
            raise

    errors: List[str] = []
    tools = _which_tools()
    # Prefer non-Keka CLIs; skip Keka.app helpers on large archives (crash + waste time)
    stable = [(n, t) for n, t in tools if not _is_keka_bundled_tool(t)]
    keka_tools = [(n, t) for n, t in tools if _is_keka_bundled_tool(t)]
    if archive_size >= 80 * 1024 * 1024:
        keka_tools = []  # go straight to Keka GUI / Homebrew
    if suffix == ".rar":
        prefer = ("unar", "unrar", "7z", "7zz", "keka-cli")
    else:
        prefer = ("7z", "7zz", "unar", "unrar", "keka-cli")

    def _order(pool: List[Tuple[str, str]]) -> List[Tuple[str, str]]:
        head = [t for name in prefer for t in pool if t[0] == name]
        tail = [t for t in pool if t not in head]
        return head + tail

    ordered = _order(stable) + _order(keka_tools)
    keka_dir = _keka_macos_dir()
    saw_password_hint = False
    t0 = time.time()

    def _poll_progress(stop: threading.Event) -> None:
        while not stop.wait(0.35):
            done, n = _dir_extracted_bytes(dest_dir)
            _emit(done, archive_size, n, time.time() - t0)

    # 1) CLI helpers — Homebrew/system first (unar preferred for RAR)
    for name, tool in ordered:
        stop = threading.Event()
        poller = threading.Thread(target=_poll_progress, args=(stop,), daemon=True)
        _emit(0, archive_size, 0, 0)
        if on_progress:
            try:
                # Signal active tool via zero-byte tick + tool name in elapsed channel misuse avoided —
                # callers read job.current; set via optional 5th convention: store on dest marker file.
                (dest_dir / ".pshd-extract-tool").write_text(f"{name}:{tool}", encoding="utf-8")
            except Exception:
                pass
        poller.start()
        try:
            cwd = str(keka_dir) if keka_dir and _is_keka_bundled_tool(tool) else None
            if name == "unar":
                cmd = [tool, "-force-overwrite", "-o", str(dest_dir)]
                if pwd:
                    cmd.extend(["-password", pwd])
                cmd.append(str(archive))
            elif name == "unrar":
                pflag = f"-p{pwd}" if pwd else "-p-"
                cmd = [tool, "x", "-o+", pflag, str(archive), str(dest_dir) + os.sep]
            elif name == "keka-cli":
                cmd = [tool, "--extract", str(archive), "--output", str(dest_dir)]
                if pwd:
                    cmd.extend(["--password", pwd])
            elif name in ("bsdtar", "tar"):
                if pwd or suffix == ".rar":
                    continue
                cmd = [tool, "-xf", str(archive), "-C", str(dest_dir)]
            elif name in ("7z", "7zz"):
                cmd = [tool, "x", "-y", f"-o{dest_dir}"]
                if pwd:
                    cmd.append(f"-p{pwd}")
                else:
                    cmd.append("-p")
                cmd.append(str(archive))
            else:
                continue
            # Short timeout for known-unstable Keka helpers
            timeout = 45 if _is_keka_bundled_tool(tool) else 60 * 90
            # Stream stdout for unar/7z so large extracts don't buffer forever; poll dir for %.
            proc = subprocess.run(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
                timeout=timeout,
                cwd=cwd,
            )
            if proc.returncode < 0:
                errors.append(f"{Path(tool).name}: crash signal {-proc.returncode} (outil Keka instable)")
                continue
            done, n = _dir_extracted_bytes(dest_dir)
            if proc.returncode == 0 and done > 0:
                _emit(done, archive_size, n, time.time() - t0)
                return
            err = (proc.stderr or "").strip() or f"exit {proc.returncode}"
            if _looks_like_password_error(err):
                saw_password_hint = True
            errors.append(f"{Path(tool).name}: {err[:240]}")
        except Exception as exc:  # noqa: BLE001
            if _looks_like_password_error(str(exc)):
                saw_password_hint = True
            errors.append(f"{name}: {exc}")
        finally:
            stop.set()
            try:
                (dest_dir / ".pshd-extract-tool").unlink(missing_ok=True)
            except Exception:
                pass

    # 2) rarfile + external unrar (never use crashing Keka unrar on big files)
    if suffix == ".rar":
        try:
            import rarfile  # type: ignore

            unrar_tool = ""
            for kind, tool in ordered:
                if kind == "unrar" and not _is_keka_bundled_tool(tool):
                    unrar_tool = tool
                    break
            if unrar_tool:
                rarfile.UNRAR_TOOL = unrar_tool
                with rarfile.RarFile(archive) as rf:
                    rf.extractall(dest_dir, pwd=pwd or None)
                done, n = _dir_extracted_bytes(dest_dir)
                if done > 0:
                    _emit(done, archive_size, n, time.time() - t0)
                    return
        except Exception as exc:  # noqa: BLE001
            if _looks_like_password_error(str(exc)):
                saw_password_hint = True
            errors.append(f"rarfile: {exc}")

    # 3) Keka GUI (best path on macOS for multi‑GiB when no Homebrew unar)
    if sys_platform_is_mac() and (
        Path("/Applications/Keka.app").exists() or (Path.home() / "Applications/Keka.app").exists()
    ):
        try:
            _extract_with_keka_applescript(archive, dest_dir, on_progress=on_progress)
            done, n = _dir_extracted_bytes(dest_dir)
            if done > 0:
                _emit(done, archive_size, n, time.time() - t0)
                return
        except Exception as exc:  # noqa: BLE001
            errors.append(f"Keka GUI: {exc}")

    if saw_password_hint:
        raise RuntimeError(
            "Archive protégée par mot de passe — renseigne le champ « Mot de passe archive » "
            "dans l’onglet Lien, puis relance."
        )

    hint = (
        "Pour les gros RAR, installe un extracteur CLI stable : `brew install unar`. "
        "Sinon extrais à la main avec Keka puis onglet Transfert."
    )
    detail = "; ".join(errors[:4]) if errors else "aucun outil RAR trouvé"
    raise RuntimeError(f"Extraction impossible ({detail}). {hint}")


def salvage_download(tmp_path: Path, filename: str) -> Path:
    """Keep a failed-extract download in ~/Downloads/PSHD-archives (don't lose multi‑GiB)."""
    dest_dir = Path.home() / "Downloads" / "PSHD-archives"
    dest_dir.mkdir(parents=True, exist_ok=True)
    safe = Path(filename or tmp_path.name).name or "archive.bin"
    dest = dest_dir / safe
    if dest.exists():
        stem, suf = dest.stem, dest.suffix
        dest = dest_dir / f"{stem}-{int(time.time())}{suf}"
    try:
        shutil.move(str(tmp_path), str(dest))
    except OSError:
        shutil.copy2(tmp_path, dest)
        try:
            tmp_path.unlink()
        except OSError:
            pass
    return dest


def sys_platform_is_mac() -> bool:
    return sys.platform == "darwin"


def _unwrap_single_dir(extract_dir: Path) -> Path:
    entries = [p for p in extract_dir.iterdir() if not p.name.startswith(".")]
    if len(entries) == 1 and entries[0].is_dir():
        return entries[0]
    return extract_dir


def _fmt_bytes(n: int) -> str:
    n = float(max(0, n))
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if n < 1024 or unit == "TiB":
            if unit == "B":
                return f"{int(n)} {unit}"
            return f"{n:.2f} {unit}"
        n /= 1024
    return f"{int(n)} B"


def validate_extracted_payload(items: List[Tuple[Path, str]], archive_path: Path) -> None:
    """Fail loudly if extract is suspiciously tiny vs the downloaded archive."""
    try:
        archive_size = archive_path.stat().st_size
    except OSError:
        return
    total = 0
    for local, _ in items:
        try:
            total += local.stat().st_size
        except OSError:
            pass
    if archive_size >= 64 * 1024 * 1024 and total < max(16 * 1024 * 1024, archive_size // 20):
        names = ", ".join(p.name for p, _ in items[:5])
        raise RuntimeError(
            f"Extraction trop légère : {_fmt_bytes(total)} pour {_fmt_bytes(archive_size)} "
            f"({len(items)} fichier(s) : {names}). "
            "Souvent un RAR multi-parties incomplet, ou extract arrêté trop tôt. "
            "Extrais le jeu entièrement avec Keka, puis utilise l’onglet Transfert."
        )


def collect_extracted_items(extract_dir: Path, dest_root: str, archive_stem: str) -> List[Tuple[Path, str]]:
    """Map extracted files → remote paths under dest_root (Mac-side layout)."""
    dest_root = _safe_remote(dest_root)
    payload = _unwrap_single_dir(extract_dir)
    if payload == extract_dir:
        base_name = archive_stem or "extracted"
        root = extract_dir
    else:
        base_name = payload.name
        root = payload
    items: List[Tuple[Path, str]] = []
    for file_path in root.rglob("*"):
        if not file_path.is_file():
            continue
        if (
            file_path.name.startswith("._")
            or file_path.name.startswith(".pshd-")
            or file_path.name == ".DS_Store"
        ):
            continue
        # Skip leftover archive copies inside extract dir
        if file_path.suffix.lower() in ARCHIVE_SUFFIXES and file_path.parent == extract_dir:
            continue
        rel = file_path.relative_to(root).as_posix()
        remote = _safe_remote(f"{dest_root}/{base_name}/{rel}")
        items.append((file_path, remote))
    if not items:
        raise RuntimeError("Archive vide après extraction")
    return items


def start_url_transfer(
    host: str,
    url: str,
    filename: str = "",
    dest_root: str = HOMEBREW_ROOT,
    password: str = "",
    extract: bool = True,
) -> TransferJob:
    url = (url or "").strip()
    if not url.startswith(("http://", "https://")):
        raise ValueError("URL http(s) requise")
    name = _filename_from_url(url, filename)
    dest_root = _safe_remote(dest_root)
    if extract and is_archive_filename(name):
        remote = _safe_remote(f"{dest_root}/{Path(name).stem}")
    else:
        remote = _remote_for_filename(dest_root, name)
    job = TransferJob(id=uuid.uuid4().hex[:12], host=host, workers=1, kind="url")
    job.total_files = 1
    job.current = name
    job.remote_path = remote
    job.source_url = url
    job.dest_root = dest_root
    with _jobs_lock:
        _jobs[job.id] = job
    threading.Thread(
        target=_run_url_job,
        args=(job, url, remote, name, dest_root, password or "", bool(extract)),
        daemon=True,
    ).start()
    return job


def _rm_tree(path: Optional[Path]) -> None:
    if not path:
        return
    try:
        if path.is_file():
            path.unlink()
        elif path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
    except OSError:
        pass


def _cleanup_url_job(
    job: TransferJob,
    tmp_path: Optional[Path],
    extract_dir: Optional[Path],
    remotes: List[str],
    *,
    remove_remote: bool,
) -> None:
    with job._lock:
        if job.cleaned:
            return
        job.cleaned = True
    _rm_tree(tmp_path)
    _rm_tree(extract_dir)
    deleted = 0
    if remove_remote:
        for remote in remotes:
            if ftp_delete_quiet(job.host, remote):
                deleted += 1
    with job._lock:
        if remove_remote and remotes:
            job.current = f"annulé · {deleted}/{len(remotes)} fichier(s) console supprimé(s)"
        else:
            job.current = "annulé · nettoyage local OK"


def _run_url_job(
    job: TransferJob,
    url: str,
    remote: str,
    filename: str,
    dest_root: str,
    password: str = "",
    extract: bool = True,
) -> None:
    job.started_at = time.time()
    job.status = "running"
    job.phase = "download"
    tmp_path: Optional[Path] = None
    extract_dir: Optional[Path] = None
    uploaded_remotes: List[str] = []
    upload_started = False
    try:
        if job_is_cancelled(job):
            raise TransferCancelled("Annulé par l’utilisateur")
        # Small HTTP chunks: BLOCKSIZE (16MiB) can exceed socket timeout on slow links.
        http_chunk = 256 * 1024
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "PSHomebrewDesk/Pixam",
                "Accept": "*/*",
                "Accept-Encoding": "identity",
            },
        )
        with urllib.request.urlopen(req, timeout=600) as resp:
            total = int(resp.headers.get("Content-Length") or 0)
            with job._lock:
                job.phase = "download"
                job.total_bytes = total
                job.download_total = total
                job.download_bytes = 0
                job.current = f"download · {filename}"
                job.remote_path = remote
            fd, tmp_name = tempfile.mkstemp(prefix="pshd-dl-", suffix=Path(filename).suffix or ".bin")
            tmp_path = Path(tmp_name)
            with os.fdopen(fd, "wb") as out:
                while True:
                    if job_is_cancelled(job):
                        raise TransferCancelled("Annulé pendant le téléchargement")
                    chunk = resp.read(http_chunk)
                    if not chunk:
                        break
                    out.write(chunk)
                    with job._lock:
                        job.sent_bytes += len(chunk)
                        job.download_bytes += len(chunk)
                        if job.total_bytes <= 0:
                            job.total_bytes = job.sent_bytes
                        if job.download_total <= 0:
                            job.download_total = job.download_bytes

        with job._lock:
            job.download_bytes = max(job.download_bytes, tmp_path.stat().st_size if tmp_path else 0)
            if job.download_total < job.download_bytes:
                job.download_total = job.download_bytes

        if job_is_cancelled(job):
            raise TransferCancelled("Annulé avant l’extraction/upload")

        archive = is_archive_filename(filename)
        if archive and extract:
            with job._lock:
                job.phase = "extract"
                job.extract_total = max(1, tmp_path.stat().st_size if tmp_path else 1)
                job.extract_bytes = 0
                job.current = f"extract · {filename} (sur cet appareil)"
            extract_dir = Path(tempfile.mkdtemp(prefix="pshd-x-"))

            def _on_extract(done: int, total: int, files: int, elapsed: float) -> None:
                tool_label = ""
                try:
                    marker = extract_dir / ".pshd-extract-tool" if extract_dir else None
                    if marker and marker.is_file():
                        tool_label = marker.read_text(encoding="utf-8").split(":", 1)[0]
                except Exception:
                    tool_label = ""
                with job._lock:
                    job.phase = "extract"
                    job.extract_bytes = max(0, int(done))
                    job.extract_total = max(1, int(total) or job.extract_total)
                    mins = int(elapsed // 60)
                    secs = int(elapsed % 60)
                    tool_bit = f"{tool_label} · " if tool_label else ""
                    job.current = (
                        f"extract · {tool_bit}{_fmt_bytes(done)} / ~{_fmt_bytes(total)} · "
                        f"{files} fic. · {mins:02d}:{secs:02d}"
                    )

            try:
                extract_archive(
                    tmp_path, extract_dir, password=password, on_progress=_on_extract
                )
            except Exception as exc:
                # Keep the multi‑GiB download — don't wipe it on extract failure
                if tmp_path and tmp_path.is_file():
                    saved = salvage_download(tmp_path, filename)
                    tmp_path = None
                    with job._lock:
                        job.status = "error"
                        job.phase = "error"
                        job.current = f"extract échoué · sauvé {saved}"
                        job.errors.append(str(exc))
                        job.errors.append(f"Archive conservée : {saved}")
                    _rm_tree(extract_dir)
                    extract_dir = None
                    job.finished_at = time.time()
                    return
                raise
            if job_is_cancelled(job):
                raise TransferCancelled("Annulé après extraction")
            items = collect_extracted_items(extract_dir, dest_root, Path(filename).stem)
            try:
                validate_extracted_payload(items, tmp_path)
            except Exception as exc:
                if tmp_path and tmp_path.is_file():
                    saved = salvage_download(tmp_path, filename)
                    tmp_path = None
                    with job._lock:
                        job.status = "error"
                        job.phase = "error"
                        job.current = f"extract incomplet · sauvé {saved}"
                        job.errors.append(str(exc))
                        job.errors.append(f"Archive conservée : {saved}")
                    _rm_tree(extract_dir)
                    extract_dir = None
                    job.finished_at = time.time()
                    return
                raise
            upload_bytes = sum(p.stat().st_size for p, _ in items)
            # Actual remote root may differ from archive stem (unwrap folder name)
            remote_roots = sorted(
                {str(Path(r.replace("\\", "/")).as_posix().rsplit("/", 1)[0] or "/") for _, r in items}
            )
            remote_display = remote_roots[0] if len(remote_roots) == 1 else remote
            with job._lock:
                job.phase = "upload"
                job.total_files = len(items)
                job.done_files = 0
                job.upload_total = upload_bytes
                job.upload_bytes = 0
                job.total_bytes = max(1, job.download_total) + upload_bytes
                job.remote_path = remote_display
                job.current = f"upload · 0/{len(items)} · {_fmt_bytes(upload_bytes)}"

            def on_bytes(n: int) -> None:
                with job._lock:
                    job.sent_bytes += n
                    job.upload_bytes += n
                _companion_notify(job, force=False)

            for idx, (local, remote_path) in enumerate(items, start=1):
                if job_is_cancelled(job):
                    raise TransferCancelled("Annulé pendant l’upload")
                with job._lock:
                    job.current = f"upload · {idx}/{len(items)} · {local.name}"
                _companion_notify(job, force=True)
                upload_started = True
                upload_file(
                    job.host,
                    local,
                    remote_path,
                    on_bytes=on_bytes,
                    should_cancel=lambda: job_is_cancelled(job),
                )
                uploaded_remotes.append(remote_path)
                with job._lock:
                    job.done_files = idx
            with job._lock:
                job.status = "done"
                job.phase = "done"
                job.upload_bytes = max(job.upload_bytes, job.upload_total)
                job.current = (
                    f"{remote_display} · {len(items)} fichier(s) · {_fmt_bytes(upload_bytes)}"
                )
            _companion_notify(job, force=True)
        else:
            downloaded = tmp_path.stat().st_size
            with job._lock:
                job.phase = "upload"
                job.download_total = max(job.download_total, downloaded)
                job.download_bytes = downloaded
                job.upload_total = downloaded
                job.upload_bytes = 0
                job.total_bytes = downloaded * 2
                job.sent_bytes = downloaded
                job.current = f"upload · {filename}"

            def on_bytes(n: int) -> None:
                with job._lock:
                    job.sent_bytes += n
                    job.upload_bytes += n
                _companion_notify(job, force=False)
            upload_started = True
            _companion_notify(job, force=True)
            upload_file(
                job.host,
                tmp_path,
                remote,
                on_bytes=on_bytes,
                should_cancel=lambda: job_is_cancelled(job),
            )
            uploaded_remotes.append(remote)
            if job_is_cancelled(job):
                raise TransferCancelled("Annulé pendant l’upload")
            with job._lock:
                job.done_files = 1
                job.status = "done"
                job.phase = "done"
                job.upload_bytes = max(job.upload_bytes, job.upload_total)
                job.current = remote
            _companion_notify(job, force=True)
    except TransferCancelled as exc:
        _cleanup_url_job(
            job,
            tmp_path,
            extract_dir,
            uploaded_remotes,
            remove_remote=upload_started,
        )
        with job._lock:
            job.status = "cancelled"
            job.phase = "cancelled"
            job.errors.append(str(exc) or "Annulé")
            if not str(job.current).startswith("annulé"):
                job.current = "annulé · fichiers nettoyés"
        tmp_path = None
        extract_dir = None
    except Exception as exc:  # noqa: BLE001
        _cleanup_url_job(
            job,
            tmp_path,
            extract_dir,
            uploaded_remotes,
            remove_remote=upload_started,
        )
        tmp_path = None
        extract_dir = None
        with job._lock:
            if job.cancel_requested:
                job.status = "cancelled"
                job.phase = "cancelled"
                job.errors.append("Annulé")
            else:
                job.status = "error"
                job.phase = "error"
                job.errors.append(str(exc))
    finally:
        _rm_tree(tmp_path)
        _rm_tree(extract_dir)
        job.finished_at = time.time()
        _companion_notify(job, force=True)
        _finish_job_side_effects(job)


def _run_job(job: TransferJob, items: List[Tuple[Path, str]]) -> None:
    job.started_at = time.time()
    job.status = "running"
    job.phase = "upload"
    total = sum(p.stat().st_size for p, _ in items if p.is_file())
    with job._lock:
        job.upload_total = total
        job.upload_bytes = 0
        job.total_bytes = total
        job.download_total = 0
        job.download_bytes = 0

    def add_bytes(n: int) -> None:
        job_wait_if_paused(job)
        if job_is_cancelled(job):
            return
        with job._lock:
            job.sent_bytes += n
            job.upload_bytes += n
        _companion_notify(job, force=False)

    def one(local: Path, remote: str) -> None:
        job_wait_if_paused(job)
        if job_is_cancelled(job):
            raise TransferCancelled("Annulé par l’utilisateur")
        with job._lock:
            job.phase = "upload"
            job.current = local.name
            job.remote_path = remote
        _companion_notify(job, force=True)
        try:
            upload_file(
                job.host,
                local,
                remote,
                on_bytes=add_bytes,
                should_cancel=lambda: job_is_cancelled(job),
            )
            with job._lock:
                job.done_files += 1
            _companion_notify(job, force=True)
        except TransferCancelled:
            raise
        except Exception as exc:  # noqa: BLE001
            with job._lock:
                job.errors.append(f"{local.name}: {exc}")
                job.done_files += 1
            _companion_notify(job, force=True)

    _companion_notify(job, force=True)
    try:
        with ThreadPoolExecutor(max_workers=job.workers) as pool:
            futures = [pool.submit(one, local, remote) for local, remote in items]
            for fut in as_completed(futures):
                if job_is_cancelled(job):
                    for pending in futures:
                        pending.cancel()
                    raise TransferCancelled("Annulé par l’utilisateur")
                fut.result()
        with job._lock:
            if job.cancel_requested:
                job.status = "cancelled"
                job.phase = "cancelled"
            else:
                job.status = "error" if job.errors and job.done_files == len(job.errors) else ("done" if not job.errors else "done_with_errors")
                job.phase = "done" if job.status.startswith("done") else "error"
            job.current = ""
            if job.upload_total:
                job.upload_bytes = min(job.upload_total, max(job.upload_bytes, job.sent_bytes))
    except TransferCancelled:
        with job._lock:
            job.status = "cancelled"
            job.phase = "cancelled"
            job.current = ""
    except Exception as exc:  # noqa: BLE001
        with job._lock:
            job.status = "error"
            job.phase = "error"
            job.errors.append(str(exc))
    finally:
        job.finished_at = time.time()
        _companion_notify(job, force=True)
        _finish_job_side_effects(job)
