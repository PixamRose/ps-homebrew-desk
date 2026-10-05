"""Push transfer status to Pixam Console ELF on the PS5 (TCP :9123)."""

from __future__ import annotations

import json
import os
import socket
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

from desk.common import app_root

DEFAULT_PORT = 9123
CONFIG_NAME = "companion.json"

_lock = threading.Lock()
_cfg: Dict[str, Any] = {
    "enabled": False,
    "host": "",
    "port": DEFAULT_PORT,
}
_last_sent: Dict[str, float] = {}
_cfg_loaded = False


def _config_path() -> Path:
    return app_root() / "cache" / CONFIG_NAME


def load_config() -> Dict[str, Any]:
    global _cfg, _cfg_loaded
    with _lock:
        if _cfg_loaded:
            return dict(_cfg)
        path = _config_path()
        try:
            if path.is_file():
                raw = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    _cfg["enabled"] = bool(raw.get("enabled"))
                    _cfg["host"] = str(raw.get("host") or "").strip()
                    try:
                        _cfg["port"] = int(raw.get("port") or DEFAULT_PORT)
                    except (TypeError, ValueError):
                        _cfg["port"] = DEFAULT_PORT
        except Exception:
            pass
        # Env overrides
        env_host = os.environ.get("DESK_COMPANION_HOST", "").strip()
        if env_host:
            _cfg["host"] = env_host
            _cfg["enabled"] = True
        env_en = os.environ.get("DESK_COMPANION", "").strip().lower()
        if env_en in ("1", "true", "yes", "on"):
            _cfg["enabled"] = True
        elif env_en in ("0", "false", "no", "off"):
            _cfg["enabled"] = False
        try:
            env_port = os.environ.get("DESK_COMPANION_PORT", "").strip()
            if env_port:
                _cfg["port"] = int(env_port)
        except ValueError:
            pass
        _cfg_loaded = True
        return dict(_cfg)


def save_config(enabled: Optional[bool] = None, host: Optional[str] = None, port: Optional[int] = None) -> Dict[str, Any]:
    global _cfg, _cfg_loaded
    with _lock:
        _cfg_loaded = True
        if enabled is not None:
            _cfg["enabled"] = bool(enabled)
        if host is not None:
            _cfg["host"] = str(host).strip()
        if port is not None:
            try:
                _cfg["port"] = int(port) or DEFAULT_PORT
            except (TypeError, ValueError):
                _cfg["port"] = DEFAULT_PORT
        path = _config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(_cfg, indent=2), encoding="utf-8")
        return dict(_cfg)


def status_payload() -> Dict[str, Any]:
    cfg = load_config()
    return {
        "ok": True,
        "enabled": bool(cfg.get("enabled")),
        "host": cfg.get("host") or "",
        "port": int(cfg.get("port") or DEFAULT_PORT),
        "protocol": "tcp-json-lines",
        "hint": "Lance pixam-console.elf sur la PS5 (elfldr :9021), puis active le companion.",
    }


def _send_line(host: str, port: int, payload: Dict[str, Any]) -> bool:
    line = (json.dumps(payload, separators=(",", ":")) + "\n").encode("utf-8")
    try:
        with socket.create_connection((host, port), timeout=0.45) as sock:
            sock.sendall(line)
        return True
    except OSError:
        return False


def notify_job(snapshot: Dict[str, Any], *, force: bool = False) -> bool:
    """Send a throttled transfer event to the console ELF."""
    cfg = load_config()
    if not cfg.get("enabled"):
        return False
    host = (cfg.get("host") or snapshot.get("host") or "").strip()
    if not host:
        return False
    port = int(cfg.get("port") or DEFAULT_PORT)
    job_id = str(snapshot.get("id") or "")
    status = str(snapshot.get("status") or "")
    now = time.time()
    with _lock:
        last = _last_sent.get(job_id, 0.0)
        terminal = status in ("done", "done_with_errors", "error", "cancelled")
        if not force and not terminal and (now - last) < 0.25:
            return False
        _last_sent[job_id] = now

    bytes_done = int(snapshot.get("upload_bytes") or snapshot.get("sent_bytes") or 0)
    bytes_total = int(snapshot.get("upload_total") or snapshot.get("total_bytes") or 0)
    event = {
        "type": "transfer",
        "id": job_id,
        "name": snapshot.get("current") or "",
        "phase": snapshot.get("phase") or "",
        "status": status,
        "bytes": bytes_done,
        "total": bytes_total,
        "percent": snapshot.get("upload_percent") or snapshot.get("percent") or 0,
        "mbps": snapshot.get("mbps") or 0,
        "eta_seconds": snapshot.get("eta_seconds"),
        "done_files": snapshot.get("done_files") or 0,
        "total_files": snapshot.get("total_files") or 0,
        "remote_path": snapshot.get("remote_path") or "",
        "errors": (snapshot.get("errors") or [])[:3],
        "ts": now,
    }
    # Non-blocking: fire in a daemon thread so FTP loop never stalls
    threading.Thread(target=_send_line, args=(host, port, event), daemon=True).start()
    return True


def notify_job_obj(job: Any, *, force: bool = False) -> bool:
    try:
        snap = job.snapshot()
    except Exception:
        return False
    # Prefer companion host; fall back to job.host (PS5)
    cfg = load_config()
    if not (cfg.get("host") or "").strip() and getattr(job, "host", None):
        save_config(host=str(job.host))
    return notify_job(snap, force=force)
