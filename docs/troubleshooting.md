# Troubleshooting

First, run the self-test. It checks the app without touching your real data (see [Command line](usage.md#command-line)):

```bash
<app folder>/launcher --selftest
```

It prints a report; each check has `"ok": true` or an error.

## I don't see the tray icon

- **Windows:** open the `^` arrow next to the clock; you can drag the icon out of it.
- **Ubuntu:** the top bar shows tray icons only with the "AppIndicator and KStatusNotifierItem Support" extension (on by default in Ubuntu). Without a tray, the app opens the Settings window instead.
- If the app is already running, starting it again brings its Settings window forward.

## Windows SmartScreen or macOS blocks the app

The files are not signed with a paid code-signing certificate. Follow the first-run steps in [Install](install.md#windows) (Windows) or [Install](install.md#macos) (macOS). You can check that the file is genuine with [Verify a download](install.md#verify-a-download).

## "MCP server stopped: address already in use"

Another program uses port 39217. Open **Settings**, change **Local MCP port** (for example to 39218), save, and restart the app (Quit, then open it again). Then copy the client setup again, because the address changes.

## A client gets 401 Unauthorized

The client sends a wrong or old key. Copy the client setup again from the tray menu and replace the old one.

If the key leaked, make a new one: quit the app, delete `vault.sqlite3` (and `vault.sqlite3-wal` and `vault.sqlite3-shm`, if present) from the app folder ([Where your data is](usage.md#where-your-data-is)), and start the app. It creates a new key; type your Siigo credentials again and copy the new client setups.

## A client does not see the write tools

That is expected while **Write actions** is OFF. Turn it on from the tray menu. Some clients need a refresh or a restart to see the new tool list. The switch turns off again every time the app starts.

## A write says "The user did not approve", but nobody asked you

**Known problem in v0.1.0.** With write actions on, a write ends at once with `rejected_by_user` ("The user did not approve … Nothing was sent."), and you never see an Approve/Reject question or a `confirmation_id`. Nothing is sent to Siigo.

**Cause.** Claude Code tells the server it can ask you questions (MCP elicitation), so the server asks it for your approval. Claude Code shows that question only in the **interactive terminal**. When Claude Code runs inside another app that doesn't show the question (the Claude Desktop app, or non-interactive mode such as `claude -p`), it answers "decline" automatically, without asking you. The server can't tell an automatic "decline" from your "no", so it rejects the write.

| Where | Write approval |
|---|---|
| Claude Code in a terminal (`claude`) | Works: an Approve/Reject question appears |
| Claude Desktop | Doesn't work: declined automatically |
| Claude Code non-interactive (`claude -p`) | Doesn't work: declined automatically |

**What to do for now:** run write actions from Claude Code in a terminal. Read actions work everywhere. A fix is planned (see the [write approval fix plan](../prompts/2026.11.19_write_approval_bug/2026.11.19_refined_write_approval_fix_v3.md)).

Turning on system notifications doesn't help: the approval is a question in the AI app, not a notification.

## Siigo errors

- **401 or "invalid credentials":** check the API username and access key in Settings (Siigo Nube → Alianzas → Mi Credencial API), then **Test connection**.
- **429 "too many requests":** Siigo limits the request rate. The app waits and retries automatically (up to 2 times). Ask the AI to request fewer pages at a time.
- **DIAN errors on an invoice:** use the read tool `siigo_get_invoice_dian_errors` to see why the DIAN rejected it.

## The vault cannot be opened

If the keychain key was deleted or changed (for example, after a system reinstall), the app offers to reset the vault. Resetting deletes the stored credentials and settings; type your Siigo credentials again.

On Ubuntu without a desktop keychain (for example, a minimal install or a remote session), the app cannot store its key. Install and unlock GNOME Keyring (`sudo apt install gnome-keyring`) and log in again.

## An update was rolled back

The new version failed its self-test, so the app kept the old one. The file `update.log` in the app folder ([Where your data is](usage.md#where-your-data-is)) has the self-test output. Please open an issue with it on [GitHub](https://github.com/neyron1002/mcp-siigo-unofficial/issues).

## "Could not check for updates"

The app could not reach GitHub (no internet, a proxy, or GitHub's request limit). Try again later, or download the new version from the [releases page](https://github.com/neyron1002/mcp-siigo-unofficial/releases) and run it: it installs over the current version.

## Report a problem

Open an issue on [GitHub](https://github.com/neyron1002/mcp-siigo-unofficial/issues) with your system, the app version (in **About**), and the self-test report. Never include your Siigo credentials, the access key, or the client setup text.
