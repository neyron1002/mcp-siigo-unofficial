# Using the app

## Tray menu

| Item | What it does |
|---|---|
| Status | Shows whether the MCP server is running and the address, or what is missing. |
| Write actions: ON/OFF | Turns write actions on (after a warning) or off. See [Write actions](#write-actions). |
| Copy client setup | Copies a ready-made setup for each AI client. See [Client setup](clients.md). |
| Settings… | Siigo credentials, connection test, language (English, Spanish, or the system's), local MCP port (used after a restart), and the write switch. |
| Start at login | Starts the app when you log in. On after the first run. |
| Check for updates | Looks for a newer release. See [Updates](#updates). |
| About | Author, license, and links. |
| Quit | Stops the app and its MCP server. |

## Write actions

Read tools only read your Siigo data. Write tools create or change **real** records in your Siigo company, and electronic invoices are sent to the DIAN (Dirección de Impuestos y Aduanas Nacionales, Colombia's tax authority). The app protects writes in four ways:

1. **Off by default.** Write tools are hidden from AI clients until you turn them on from the tray menu or Settings. The switch turns off again every time the app starts.
2. **Your acceptance.** Turning them on shows a warning, and the **Enable** button works only after you tick "I understand and accept responsibility".
3. **Visible.** While write actions are on, the tray icon has a red badge and the system shows a notification.
4. **Approval of every write.** Each write needs your approval. If your AI client supports it (MCP elicitation), it shows an Approve/Reject question. Otherwise the first call only returns a preview and a one-time code (`confirmation_id`, valid for 5 minutes, for those exact arguments); the AI must show you the preview and use the code only after you approve.

   **Known limit (v0.1.0):** the Approve/Reject question appears in Claude Code in a terminal. In Claude Desktop, the question never appears and every write is rejected. See [Troubleshooting](troubleshooting.md#a-write-says-the-user-did-not-approve-but-nobody-asked-you).

Turn write actions off when you finish. You are responsible for the actions your AI client executes; see the [disclaimer](../README.md#disclaimer-and-liability).

## Updates

**Check for updates** asks GitHub for a newer release. If there is one, the app asks before installing it. Then it:

1. downloads the file for your system;
2. checks its Ed25519 signature against the public key built into the app, and its SHA-256 (a file that fails is deleted);
3. quits, installs the new version beside the old one, and runs the new version's self-test;
4. starts the new version only if the self-test passes. Otherwise it keeps the old version (rollback) and tells you.

The previous version is always kept. After an update, write actions are off, like after every start. The app also checks quietly 20 seconds after it starts and only shows a notification. Test versions (`-rc.N`) are offered only to people who installed a test version.

## Where your data is

| | Windows | macOS | Ubuntu |
|---|---|---|---|
| App and data | `%LOCALAPPDATA%\MCPSiigoUnofficial\` | `~/Library/Application Support/MCPSiigoUnofficial/` | `~/.local/share/mcp-siigo-unofficial/` |
| Vault key | Credential Manager | Keychain | Secret Service (GNOME Keyring or KWallet) |

- `vault.sqlite3` is the encrypted vault (AES-256-GCM). It holds your Siigo credentials, the private server key for AI clients, your settings, and a log of write-switch changes and writes. The key that opens it is kept in your system's keychain, under the name `mcp-siigo-unofficial`.
- `versions/` holds the installed version and the previous one; `current` and `previous` name them.
- `update.log` and `update-result.json` describe the last update.

Nothing is sent anywhere except to the Siigo API (your requests) and to GitHub (the update check and downloads).

## Command line

| Command | What it does |
|---|---|
| `launcher --stdio` | MCP server over stdio (what Claude Desktop and Codex run). |
| `launcher --selftest [--offline]` | Checks Qt, the vault, the MCP server, and (unless `--offline`) HTTPS, without touching your real data. |
| `launcher --update-now` | Checks for an update, downloads it, verifies it, and installs it without the tray. |
| `launcher --uninstall [--purge-data]` | Disconnects the AI apps, then see [Uninstall](install.md#uninstall). |
| `launcher --list-clients` | Shows each AI app (Claude Code, Claude Desktop, Codex, Gemini CLI, VS Code) and whether the Siigo server is connected. Output is JSON. |
| `launcher --connect-clients [--client NAME] [--transport stdio\|http] [--on-conflict ask\|keep-both\|replace]` | Adds the Siigo server to the AI apps found (all, or each `--client`), for every project of your user. stdio is the default; Claude Desktop always uses stdio. A backup `<file>.siigo-backup-<date>` is made first, and only the Siigo entry changes. If another program already uses the name `siigo`, it stops and asks (`ask`), unless you choose `keep-both` (ours is added as `siigo-unofficial`) or `replace`. |
| `launcher --disconnect-clients [--client NAME]` | Removes only the Siigo entries this app added. |
| `launcher --repair-clients` | Fixes the Siigo entries after the app moved to another folder. |

`launcher` is in the app folder above (`launcher.exe` on Windows). On macOS, use `"/Applications/MCP Siigo Unofficial.app/Contents/MacOS/MCPSiigoUnofficial"` with the same options.
