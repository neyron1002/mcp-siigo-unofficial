# Dev container

All development of MCP Siigo Unofficial happens inside this container. The host computer runs only Docker Desktop and VS Code.

## Isolation

- The only host path shared with the container is the workspace folder, mounted at `/workspace`.
- Nothing else is shared: no home folder, no Claude Code settings or login, no SSH or GPG agents, no Docker socket.
- The Python virtual environment lives in the container, at `/home/vscode/.venv`, not on the host disk.
- You sign in to Claude Code and to GitHub (`gh auth login`) inside the container. A rebuild deletes both logins on purpose, so you sign in again after each rebuild.

VS Code can still copy some host settings into a container. To turn that off, add these lines to your VS Code **user** settings once:

```json
"dev.containers.copyGitConfig": false,
"dev.containers.gitCredentialHelperConfigLocation": "none",
"dev.containers.dockerCredentialHelper": false
```

The commit identity is set in the repository by `post-create.sh`, so commits work without the host `~/.gitconfig`.

## Open it

1. In VS Code: Command Palette → **Dev Containers: Reopen in Container**.
2. Wait for `post-create.sh` to finish.
3. Sign in to Claude Code, and run `gh auth login`.

## What is inside

Ubuntu 22.04, uv with Python 3.12, git, the GitHub CLI, the Claude Code CLI, the Qt runtime libraries for PySide6, xvfb (a virtual screen for headless UI tests), and gnome-keyring (for vault tests).
