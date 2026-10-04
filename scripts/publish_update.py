#!/usr/bin/env python3
"""Publish a LAN update package: python3 scripts/publish_update.py "notes"."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from desk.update_channel import build_update_zip  # noqa: E402


def main() -> None:
    notes = " ".join(sys.argv[1:]).strip()
    manifest = build_update_zip(notes=notes)
    print(f"Version  {manifest['version']}")
    print(f"Fichiers {manifest['file_count']}")
    print(f"ZIP      {manifest['bytes']} bytes")
    print(f"SHA-256  {manifest['sha256']}")
    print(f"URL LAN  {manifest['lan_url']}")


if __name__ == "__main__":
    main()
