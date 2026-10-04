#!/bin/bash
cd "$(dirname "$0")"
export PATH="$HOME/Library/Python/3.9/bin:/usr/local/bin:/opt/homebrew/bin:$PATH"
export DESK_LAN=1
export DESK_HOST=0.0.0.0
echo "PS Homebrew Desk · LAN — by Pixam"
if [[ -z "${DESK_TOKEN:-}" ]]; then
  echo "[!] Conseil: export DESK_TOKEN=ton-secret avant le LAN"
fi
python3 desktop.py
