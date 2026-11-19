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

## A write was refused, or no approval window appeared

Every write waits for your answer in the Siigo approval window ([Approval window](usage.md#approval-window)). Nothing is sent to Siigo unless you approve.

- **"Rejected in the Siigo approval window"**: you (or Escape, or closing the window) rejected it.
- **"Nobody answered the approval window"**: the window waited 2 minutes. Look for it behind other windows, or for the notification, and ask the AI to try again.
- **"The MCP Siigo Unofficial app is not reachable"**: the tray app isn't running, or a stdio setup can't reach it (for example, the local port changed and the app wasn't restarted). Open the app and try again.
- **"The user rejected … in your app's approval question"**: in the **In the AI app** mode, you (or the AI app, after more than 1 second) said no in the AI app's question.
- **No window, only a notification**: the mode is **Notification first**. Click the notification, or wait 15 seconds.

**Before v0.1.1:** the app asked the AI app to show the question (MCP elicitation). Claude Desktop answered "decline" automatically, so every write failed there with "The user did not approve". v0.1.1 shows its own window instead, which works with every AI app.

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
