# Client setup

The tray menu has **Copy client setup** with a ready-made setup for each client below. It puts the exact text on your clipboard, with your local address and private server key filled in. Paste it where this page says.

The app offers two ways to connect:

- **HTTP** (Claude Code, GitHub Copilot in VS Code, Gemini CLI): the client connects to `http://127.0.0.1:39217/mcp` with your private bearer key. The tray app must be running. The port can be changed in Settings.
- **stdio** (Claude Desktop, Codex): the client starts the server itself with the installed launcher and `--stdio`. Write actions still follow the switch in the tray app.

The setup text contains your private server key. Don't share it or commit it to a repository. If it leaks, see [Troubleshooting](troubleshooting.md#a-client-gets-401-unauthorized).

## Claude Code

Choose **Copy client setup → Claude Code** and run the copied command in a terminal. It looks like this:

```bash
claude mcp add --transport http siigo http://127.0.0.1:39217/mcp --header "Authorization: Bearer <your key>"
```

Add `--scope user` after `add` to use it in every project. Check it with `claude mcp list`, or with `/mcp` inside Claude Code.

## Claude Desktop

Choose **Copy client setup → Claude Desktop**. In Claude Desktop, open **Settings → Developer → Edit Config**. This opens `claude_desktop_config.json`:

- Windows: `%APPDATA%\Claude\claude_desktop_config.json`
- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`

Paste the `siigo` entry inside `mcpServers` (keep any servers that are already there), save, and restart Claude Desktop. The entry starts the installed launcher:

```json
{
  "mcpServers": {
    "siigo": { "command": "<install folder>/launcher", "args": ["--stdio"] }
  }
}
```

## Codex

Choose **Copy client setup → Codex** and add the copied lines to `~/.codex/config.toml` (on Windows, `%USERPROFILE%\.codex\config.toml`):

```toml
[mcp_servers.siigo]
command = "<install folder>/launcher"
args = ["--stdio"]
```

Restart Codex, then check with `/mcp`.

## GitHub Copilot in VS Code

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

## Gemini CLI

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

En el menú del icono, elija **Copiar configuración del cliente** y el nombre de su cliente de IA. El texto copiado ya tiene su dirección local y su clave privada; péguelo donde indica cada sección de esta página (Claude Code: ejecute el comando en una terminal; Claude Desktop: `claude_desktop_config.json`; Codex: `~/.codex/config.toml`; Copilot en VS Code: `.vscode/mcp.json`; Gemini CLI: `~/.gemini/settings.json`). No comparta ese texto: contiene su clave privada.
