"""Optional Discord webhook for release / update announcements (by Pixam)."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional

from desk.common import app_root

CONFIG_NAME = "discord-webhook.json"


def _path() -> Path:
    return app_root() / "cache" / CONFIG_NAME


def get_webhook() -> str:
    env = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
    if env:
        return env
    try:
        if _path().is_file():
            data = json.loads(_path().read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return str(data.get("url") or "").strip()
    except Exception:
        pass
    return ""


def save_webhook(url: str) -> str:
    url = (url or "").strip()
    _path().parent.mkdir(parents=True, exist_ok=True)
    _path().write_text(json.dumps({"url": url}, indent=2) + "\n", encoding="utf-8")
    return url


def post_update(manifest: Dict[str, Any]) -> Dict[str, Any]:
    url = get_webhook()
    if not url:
        return {"ok": False, "skipped": True, "error": "Pas de webhook Discord configuré"}
    version = manifest.get("version") or "?"
    notes = (manifest.get("notes") or "").strip() or "Nouvelle update Desk"
    lan = manifest.get("lan_url") or ""
    content = (
        f"**PS Homebrew Desk v{version}** — by Pixam\n"
        f"{notes}\n"
        + (f"Download LAN: `{lan}`\n" if lan else "")
        + "https://github.com/PixamRose/ps-homebrew-desk/releases"
    )
    body = {
        "username": "Pixam Desk",
        "embeds": [
            {
                "title": f"Update v{version}",
                "description": notes[:1800],
                "color": 0x2EE6D6,
                "footer": {"text": "Pixam · PS Homebrew Desk"},
            }
        ],
        "content": content[:1800],
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": "PSHomebrewDesk/Pixam"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            return {"ok": True, "status": getattr(resp, "status", 204)}
    except urllib.error.HTTPError as exc:
        return {"ok": False, "error": f"Discord HTTP {exc.code}"}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}
