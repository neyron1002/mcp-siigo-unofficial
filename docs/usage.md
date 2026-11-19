# Using the app

## Tray menu

| Item | What it does |
|---|---|
| Status | Shows whether the MCP server is running and the address, or what is missing. |
| Write actions: ON/OFF | Turns write actions on (after a warning) or off. See [Write actions](#write-actions). |
| Similar writes approved … / Stop approving similar writes now | Shown only while an "approve similar writes for 10 minutes" grant is active. See [Approval window](#approval-window). |
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
4. **Approval of every write.** Each write waits for your answer in the **Siigo approval window** (below). The AI app can't answer it: only a click on your computer can.

### Approval window

When an AI app asks for a write, the app opens a window on top of your other windows and shows a notification:

- **What:** the action (for example "Create product"), its main fields (code, name, customer, number of items), and the AI app that asked. **Show details** shows the full request.
- **Approve** sends this one request to Siigo. **Reject** (or Escape, or closing the window) sends nothing.
- **Approve similar writes for 10 minutes** approves this request and, for 10 minutes, the same action from the same AI app connection runs without asking (useful for "create these 20 products"). While it lasts, the tray menu shows the time left and **Stop approving similar writes now**. It also ends when write actions turn off or the app restarts.
- **2 minutes** to answer: then the window closes, and the write is refused ("Nobody answered"). The AI is told that nothing was sent.
- Works with every AI app (Claude Code, Claude Desktop, Codex, Gemini CLI, VS Code), for both HTTP and stdio setups. A stdio server asks the running tray app through its local server, so the app must be running (write actions are off when it isn't).

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
| `launcher --uninstall [--purge-data]` | See [Uninstall](install.md#uninstall). |

`launcher` is in the app folder above (`launcher.exe` on Windows). On macOS, use `"/Applications/MCP Siigo Unofficial.app/Contents/MacOS/MCPSiigoUnofficial"` with the same options.
