# CLAUDE.md — MCP Siigo Unofficial

Rules for every AI session in this repository. The approved plan is the source of truth:
`prompts/2026.11.18_project_inception/2026.11.18_refined_project_inception_v8.md` (the latest `refined_*_vN.md` wins).

## Hard rules

1. **Dev container only.** Run project commands only inside the dev container (`/workspace`). Never install, run, test, or build on the host computer. If `/workspace` does not exist, stop: you are on the host.
2. **Smallest build.** The release file includes only the libraries, Qt modules, and plugins the app needs (plan section 3.2). Every new runtime dependency needs a size justification in its pull request. No UPX. Bytecode optimize level 1, never 2 (FastMCP reads tool descriptions from docstrings).
3. **Write safety.** Siigo write tools are behind the "Write actions" switch: off by default, and off again after every restart. Turning it on needs the warning dialog and an acceptance of responsibility. Every write needs the user's approval, in the way the user chose in Settings: the Siigo window (default), a notification that opens it, or the AI app's question with the window as fallback. Approving similar writes, or automatic approval for a limited time, only happens when the user turns it on in the app, never from an MCP tool, and it ends at its time limit, its write limit, or at restart (plan section 5.1). Never weaken this further without the owner's decision.
4. **Secrets.** Never commit, log, or print Siigo credentials, tokens, the vault master key, or the Ed25519 private key. Real Siigo credentials are typed only by the owner, in the app's Settings dialog.
5. **References.** `references/` is local reference material, ignored by git. `references/existing_mcp/mcp_siigo` is the owner's own earlier Siigo MCP server (authorship confirmed on 2026-11-18): its code, catalog, and docs may be adapted into `src/` under MIT. Do not research or compare other people's public servers unless the owner asks. Analysis: `docs/reference_mcp_analysis.md`.
6. **Prompts log.** Save every owner prompt verbatim in `prompts/raw/<YYYY.MM.DD>_<topic>/<YYYY.MM.DD>_raw_<topic>.md`. `prompts/raw/` is private (ignored by git) and is never linked from published files. Save refinements as `prompts/<YYYY.MM.DD>_<topic>/<YYYY.MM.DD>_refined_<topic>_vN.md`, next to the topic's execution log; these are published.

## Workflow

- One branch and one pull request per phase (`phase-0-foundation`, `phase-1-siigo-vault`, …). Conventional Commits. Merge only when CI is green.
- Releases: SemVer tags `vX.Y.Z`. Test releases are `vX.Y.Z-rc.N`, marked as pre-releases.
- Tooling: Python 3.12 via uv, ruff (lint and format), mypy (strict on `src/`), pytest.
- Language: code, comments, commits, and docs in English. The README has a Spanish section. UI strings are in English and Spanish.

## Owner preferences

- The owner is learning professional English. End each reply to the owner with short English corrections of their last message.
- Explain any abbreviation in the same sentence where it first appears.
