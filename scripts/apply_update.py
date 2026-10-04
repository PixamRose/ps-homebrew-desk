#!/usr/bin/env python3
"""Apply a Desk update zip (local file or LAN URL).

Examples:
  python3 scripts/apply_update.py updates/latest.zip
  python3 scripts/apply_update.py http://192.168.1.10:8787/updates/latest.zip
"""

from __future__ import annotations

import sys
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from update_channel import apply_update_zip  # noqa: E402


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    src = sys.argv[1].strip()
    if src.startswith("http://") or src.startswith("https://"):
        with tempfile.NamedTemporaryFile(prefix="pshd-upd-", suffix=".zip", delete=False) as tmp:
            tmp_path = Path(tmp.name)
        print(f"Téléchargement {src} …")
        urllib.request.urlretrieve(src, tmp_path)
        zip_path = tmp_path
    else:
        zip_path = Path(src).expanduser().resolve()
    result = apply_update_zip(zip_path, ROOT)
    print(f"OK — {result['written']} fichiers · version locale maintenant {result['version']}")
    print("Relance Desk (desktop.py / start.bat / start.command).")


if __name__ == "__main__":
    main()
