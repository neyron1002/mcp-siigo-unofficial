#!/usr/bin/env bash
# Run a command with a temporary, unlocked Secret Service keychain (Linux only).
# Used by CI and the dev container to test the vault with a real OS keychain.
# The keychain lives in a throwaway folder and is deleted afterwards; it never
# holds real secrets.
#
# Usage: scripts/with-test-keyring.sh uv run pytest
set -euo pipefail

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
export XDG_DATA_HOME="$tmp/data"
mkdir -p "$XDG_DATA_HOME"
export MCP_SIIGO_TEST_REAL_KEYRING=1

exec dbus-run-session -- bash -c '
  printf "throwaway-test-keyring" | gnome-keyring-daemon --unlock --components=secrets >/dev/null
  exec "$@"
' bash "$@"
