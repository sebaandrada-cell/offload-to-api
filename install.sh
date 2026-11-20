#!/usr/bin/env bash
# install.sh - Sets up the offload-to-api scripts in ~/.offload-to-api (or $OFFLOAD_HOME).
# Creates a private Python virtual environment, installs the Anthropic SDK and copies
# the scripts. It does not touch your shell profile and does not create any API key.
set -euo pipefail

SRC="$(cd "$(dirname "$0")" && pwd)/plugins/offload-to-api/scripts"
DEST="${OFFLOAD_HOME:-$HOME/.offload-to-api}"

command -v python3 >/dev/null || { echo "python3 not found. Install Python 3.9 or later first."; exit 1; }

mkdir -p "$DEST/scripts"
cp "$SRC"/*.py "$SRC/requirements.txt" "$DEST/scripts/"

if [ ! -x "$DEST/venv/bin/python" ]; then
  python3 -m venv "$DEST/venv"
fi
"$DEST/venv/bin/pip" install --quiet --upgrade -r "$DEST/scripts/requirements.txt"

if [ ! -f "$DEST/.env" ]; then
  printf '# Optional. Leave empty to use `ant auth login`.\n# ANTHROPIC_API_KEY=\n' > "$DEST/.env"
fi
chmod 600 "$DEST/.env"

echo "Installed in $DEST"
echo
echo "Next step, authentication (pick one):"
echo "  - Recommended: install the Anthropic CLI and run: ant auth login"
echo "  - Or put ANTHROPIC_API_KEY=... in $DEST/.env (do NOT export it in your shell profile)"
echo
echo "Try it without spending anything:"
echo "  $DEST/venv/bin/python $DEST/scripts/compare_configs.py --help"
