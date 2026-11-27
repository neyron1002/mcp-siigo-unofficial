# Client setup

## One click (recommended)

1. Open **Connect AI apps…** in the tray menu (**AI apps ▸ Connect AI apps…**). The window also opens by itself on the first start, and once after the update from 0.1.x, when an AI app is installed.
2. The window lists Claude Code, Claude Desktop, Codex, Gemini CLI, and VS Code (GitHub Copilot). The apps found on your computer are ticked.
3. Click **Connect**. The Siigo tools are added for every project and new session of your computer user. No administrator password is needed.
4. Open a new session in Claude Code, Codex, Gemini CLI, or VS Code. For Claude Desktop, click **Restart Claude Desktop** in the window (or quit and reopen it).
5. Check it: ask your AI app "Use the siigo tools: show the server status." In Claude Code, Codex, and Gemini CLI, `/mcp` also lists `siigo`.

What the app changes, and what it never does:

- It uses each AI app's own `mcp add` command when it finds it, and otherwise edits the app's settings file. Before the first change of the day, the file is copied to `<file>.siigo-backup-<date>`.
- Only the `siigo` entry changes. Your other servers and settings stay as they were. A settings file that isn't valid is never overwritten: the window shows "Settings file can't be read".
- If another program already uses the name `siigo` (for example an older Siigo server), the window asks: **Replace** it, **Keep both** (this app is added as `siigo-unofficial`), or **Skip**.
- **Disconnect** (per app) and **Disconnect all** remove only the entries this app added.
- When the app finds a new AI app later, it shows a notification. Nothing is connected until you click.
- If you move the app to another folder, it updates its own entries at the next start and tells you.
- Uninstalling the app (`--uninstall`) disconnects the AI apps first.

The same actions are available on the command line: see [Command line](usage.md#command-line).

## stdio or HTTP?

The window connects every app with **stdio** unless you choose otherwise under **Advanced: connection type for each app**.

| | stdio (recommended) | HTTP |
|---|---|---|
| How it works | The AI app starts the Siigo server itself (`launcher --stdio`), one process per AI session | The AI app connects to the tray app's local server at `http://127.0.0.1:39217/mcp` |
| Private key in the AI app's settings | None | Yes (a bearer key) |
| Tray app must be running | Only for writes (write actions turn off when it quits) | Always |
| Apps | All, including Claude Desktop | Claude Code, Codex, Gemini CLI, VS Code. Not Claude Desktop |
| Memory | About 80 MB per open AI session | One shared process |

Both use the same Siigo login: the token is shared through the encrypted vault, so each session doesn't log in again. Setups you made by hand with HTTP show as **Connected · HTTP**, and the window offers **Switch to stdio**.

## Manual setup

The tray menu also has **Copy client setup**, with a ready-made setup for each client below. It puts the exact text on your clipboard, with your local address and private server key filled in. Paste it where this page says.

- **HTTP** (Claude Code, GitHub Copilot in VS Code, Gemini CLI): the client connects to `http://127.0.0.1:39217/mcp` with your private bearer key. The tray app must be running. The port can be changed in Settings.
- **stdio** (Claude Desktop, Codex): the client starts the server itself with the installed launcher and `--stdio`. Write actions still follow the switch in the tray app.

The setup text contains your private server key. Don't share it or commit it to a repository. If it leaks, see [Troubleshooting](troubleshooting.md#a-client-gets-401-unauthorized).

### Claude Code

Choose **Copy client setup → Claude Code** and run the copied command in a terminal. It looks like this:

```bash
claude mcp add --transport http siigo http://127.0.0.1:39217/mcp --header "Authorization: Bearer <your key>"
```

Add `--scope user` after `add` to use it in every project. Check it with `claude mcp list`, or with `/mcp` inside Claude Code.

### Claude Desktop

Choose **Copy client setup → Claude Desktop**. In Claude Desktop, open **Settings → Developer → Edit Config**. This opens `claude_desktop_config.json`:

- Windows, classic installer: `%APPDATA%\Claude\claude_desktop_config.json`
- Windows, Microsoft Store (MSIX) package: `%LOCALAPPDATA%\Claude-Data\claude_pzs8sxrjxfjjc\claude_desktop_config.json` in newer versions, `%LOCALAPPDATA%\Packages\Claude_pzs8sxrjxfjjc\LocalCache\Roaming\Claude\claude_desktop_config.json` in older ones.
- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`

Paste the `siigo` entry inside `mcpServers` (keep any servers that are already there), save, and restart Claude Desktop. The entry starts the installed launcher:

```json
{
  "mcpServers": {
    "siigo": { "command": "<install folder>/launcher", "args": ["--stdio"] }
  }
}
```

### Codex

Choose **Copy client setup → Codex** and add the copied lines to `~/.codex/config.toml` (on Windows, `%USERPROFILE%\.codex\config.toml`):

```toml
[mcp_servers.siigo]
command = "<install folder>/launcher"
args = ["--stdio"]
```

Restart Codex, then check with `/mcp`.

### GitHub Copilot in VS Code

Choose **Copy client setup → GitHub Copilot in VS Code**. Paste it into `.vscode/mcp.json` in your project, or run **MCP: Open User Configuration** from the Command Palette to use it in every project:

```json
{
  "servers": {
    "siigo": {
      "type": "http",
      "url": "http://127.0.0.1:39217/mcp",
      "headers": { "Authorization": "Bearer <your key>" }
    }
  }
}
```

Open Copilot Chat in **Agent** mode. The Siigo tools appear in the tools list. Don't commit a `.vscode/mcp.json` that holds your key.

### Gemini CLI

Choose **Copy client setup → Gemini CLI** and merge it into `~/.gemini/settings.json`:

```json
{
  "mcpServers": {
    "siigo": {
      "httpUrl": "http://127.0.0.1:39217/mcp",
      "headers": { "Authorization": "Bearer <your key>" }
    }
  }
}
```

Restart Gemini CLI and check with `/mcp`.

## Try it

Ask your AI client: "Use the siigo tools: show the server status, then list my last 5 invoices." The status tool shows whether your Siigo credentials are set and whether write actions are on. The tools are listed in [MCP tools](tools.md).

---

## Español

**Un clic (recomendado):** en el menú del icono, abra **Apps de IA ▸ Conectar apps de IA…** (la ventana también se abre sola en el primer inicio). Las apps encontradas (Claude Code, Claude Desktop, Codex, Gemini CLI y VS Code) quedan marcadas: haga clic en **Conectar**. Luego abra una sesión nueva en su app de IA; para Claude Desktop, use **Reiniciar Claude Desktop**. Solo cambia la entrada `siigo`, se guarda una copia de respaldo del archivo de configuración y sus otros servidores no cambian. **Desconectar** quita solo lo que esta app agregó. En **Avanzado** puede elegir stdio (recomendado, sin claves en la configuración) o HTTP para cada app.

**Configuración manual:** en el menú del icono, elija **Copiar configuración del cliente** y el nombre de su cliente de IA. El texto copiado ya tiene su dirección local y su clave privada; péguelo donde indica cada sección de esta página (Claude Code: ejecute el comando en una terminal; Claude Desktop: `claude_desktop_config.json`; Codex: `~/.codex/config.toml`; Copilot en VS Code: `.vscode/mcp.json`; Gemini CLI: `~/.gemini/settings.json`). No comparta ese texto: contiene su clave privada.
