#!/usr/bin/env bash
# Runs once inside the container after it is created.
set -euo pipefail

# The workspace is owned by the host user; tell git it is safe inside the container.
git config --global --add safe.directory /workspace

# Commit identity is stored in the repository (.git/config), so the host
# ~/.gitconfig is not needed in the container.
git config --local user.name "Juan Manuel Pedraza"
git config --local user.email "juanpedraza1002@gmail.com"

# Install project dependencies once the Python project exists (phase 0).
if [ -f pyproject.toml ]; then
  uv sync --all-groups
fi

echo
echo "Dev container ready. Next, inside this container:"
echo "  1. Sign in to Claude Code (open the Claude Code panel or run: claude)"
echo "  2. gh auth login"
echo "  3. Start the session with prompts/2026.11.18_unattended_execution/2026.11.18_refined_kickoff_v1.md"
