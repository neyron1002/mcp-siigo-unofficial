# CLAUDE.md — MCP Siigo Unofficial

Rules for every AI session in this repository. The approved plan is the source of truth:
`prompts/2026.11.18_project_inception/2026.11.18_refined_project_inception_v8.md` (the latest `refined_*_vN.md` wins).

## Hard rules

1. **Dev container only.** Run project commands only inside the dev container (`/workspace`). Never install, run, test, or build on the host computer. If `/workspace` does not exist, stop: you are on the host.
2. **Smallest build.** The release file includes only the libraries, Qt modules, and plugins the app needs (plan section 3.2). Every new runtime dependency needs a size justification in its pull request. No UPX. Bytecode optimize level 1, never 2 (FastMCP reads tool descriptions from docstrings).
3. **Write safety.** Siigo write tools are behind the "Write actions" switch: off by default, and off again after every restart. Turning it on needs the warning dialog and an acceptance of responsibility. Every write needs the user's approval, through elicitation or a one-time `confirmation_id` that the server enforces (plan section 5.1). Never weaken this.
4. **Secrets.** Never commit, log, or print Siigo credentials, tokens, the vault master key, or the Ed25519 private key. Real Siigo credentials are typed only by the owner, in the app's Settings dialog.
5. **References.** `references/existing_mcp/` is local reference material, ignored by git. Do not copy its code into `src/` unless the owner confirmed authorship (see the kickoff prompt). Otherwise, reuse ideas only.
6. **Prompts log.** Save every owner prompt verbatim in `prompts/<YYYY.MM.DD>_<topic>/<YYYY.MM.DD>_raw_<topic>.md`, and save refinements as `..._refined_<topic>_vN.md`.

## Workflow

- One branch and one pull request per phase (`phase-0-foundation`, `phase-1-siigo-vault`, …). Conventional Commits. Merge only when CI is green.
- Releases: SemVer tags `vX.Y.Z`. Test releases are `vX.Y.Z-rc.N`, marked as pre-releases.
- Tooling: Python 3.12 via uv, ruff (lint and format), mypy (strict on `src/`), pytest.
- Language: code, comments, commits, and docs in English. The README has a Spanish section. UI strings are in English and Spanish.

## Owner preferences

- The owner is learning professional English. End each reply to the owner with short English corrections of their last message.
- Explain any abbreviation in the same sentence where it first appears.
