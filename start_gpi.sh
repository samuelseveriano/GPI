#!/usr/bin/env sh
# Modo desenvolvimento (Linux/macOS). No Windows use Start_GPI.bat.
cd "$(dirname "$0")" || exit 1
PYTHONPATH="$(pwd)/backend" exec python3 -m gpi.main "$@"
