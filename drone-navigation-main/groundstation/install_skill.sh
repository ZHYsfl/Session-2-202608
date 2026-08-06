#!/usr/bin/env bash
# Install the crazyflie-groundstation skill into the OpenClaw workspace so
# the gateway agent can discover it (needs an OpenClaw restart to take
# effect, like any skill change).
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/skills/crazyflie-groundstation" && pwd)"
DEST_DIR="${OPENCLAW_WORKSPACE_SKILLS:-$HOME/.openclaw/workspace/skills}"
DEST="$DEST_DIR/crazyflie-groundstation"

mkdir -p "$DEST"
cp -f "$SRC/SKILL.md" "$DEST/SKILL.md"
echo "[skill] installed -> $DEST/SKILL.md"
echo "[skill] restart OpenClaw gateway (openclaw gateway stop; start again) to load it."
