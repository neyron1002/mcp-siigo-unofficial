# MCP Siigo Unofficial

> **Download:** [latest release](https://github.com/neyron1002/mcp-siigo-unofficial/releases/latest) for Windows, macOS, and Ubuntu. Start with the [install guide](docs/install.md).

**MCP Siigo Unofficial** connects AI assistants such as Claude, Codex, Copilot, and Gemini to your Siigo accounting data. I built it for a friend's company, and for anyone who needs it: business owners, accountants, and accounting professionals. It is free of charge.

**Juan Manuel Pedraza**, a systems engineer from Bogotá, Colombia, with 16 years of experience. I am a full-stack developer, Forward Deployed Engineer, and AI Builder.

Do you need an AI automation built for your company's specific needs? Do you want a professional to guide you as you bring AI into your company's processes? [Contact me on LinkedIn](https://www.linkedin.com/in/juanpedraza1002/).

Not affiliated with Siigo S.A.S. Free, provided "as is", without warranty. MIT License. This MCP is only a bridge to the Siigo API: you are responsible for the actions your AI client executes with it, and the author is not responsible for AI decisions or executions.

## Disclaimer and liability

- MCP means Model Context Protocol, the open standard that lets AI assistants call external tools.
- Siigo is a trademark of Siigo S.A.S. This project is **not** affiliated with, endorsed by, or supported by Siigo S.A.S.
- The software is provided under the [MIT License](LICENSE), "as is", without warranty of any kind.
- Write actions (creating customers, invoices, and other records) create **real** records in Siigo, and invoices are sent to the DIAN (Dirección de Impuestos y Aduanas Nacionales, Colombia's tax authority). They are **off by default**, they turn off again every time the app restarts, and every write needs your explicit approval.
- You are fully responsible for every action your AI client executes through this MCP server. The author is not responsible for AI decisions or executions.

## What it does

A single downloadable file per operating system (Windows 10/11 x64, macOS 13+ on Apple silicon, Ubuntu 22.04/24.04 x64). It installs itself into your user folder with no administrator rights, and it runs as a tray app:

- A local MCP server (Streamable HTTP on `127.0.0.1` with a private bearer key, plus a `--stdio` mode) with 45 read tools for Siigo catalogs, customers, products, invoices, credit notes, cash receipts, journals, and reports. See [MCP tools](docs/tools.md).
- 9 write tools behind a **"Write actions" switch**, with a warning dialog, a red tray badge while enabled, and your approval of every write, in the mode you choose: the app's own approval window (default), a notification that opens it, or the AI app's question. Optional "approve similar writes for 10 minutes", and a guarded automatic approval for 1 hour or the day. See [Write actions](docs/usage.md#write-actions).
- Siigo credentials stored in an encrypted local vault (AES-256-GCM, with the master key in the operating-system keychain). Only you type them, in the Settings dialog.
- Signed updates (SHA-256 checksums signed with Ed25519) that ask before installing, run a self-test, and roll back if it fails.
- Start at login, English and Spanish interface, and "Copy client setup" for Claude Code, Claude Desktop, Codex, GitHub Copilot in VS Code, and Gemini CLI.

## Documentation

| Guide | Contents |
|---|---|
| [Install](docs/install.md) | Download, first run on each system, Siigo API credentials, verify a download, uninstall |
| [Client setup](docs/clients.md) | Claude Code, Claude Desktop, Codex, GitHub Copilot in VS Code, Gemini CLI |
| [Using the app](docs/usage.md) | Tray menu, write actions, updates, where your data is, command line |
| [MCP tools](docs/tools.md) | Every tool and the Siigo API endpoint it calls |
| [Troubleshooting](docs/troubleshooting.md) | Tray icon, blocked app, port in use, 401 errors, vault, updates |

## Roadmap

| Phase | Output |
|---|---|
| 0 Foundation | Dev container, license, README, project tooling, CI on 3 operating systems, reference analysis |
| 1 Siigo client + vault | Authentication and token renewal, encrypted vault, mock Siigo server |
| 2 MCP server | HTTP + stdio, tool catalog, write switch gate, write approval (approval window since v0.1.1) |
| 3 Tray + UI | Tray icon, Settings, About, English/Spanish, start at login, write-enable warning |
| 4 Single-file build | Launcher with embedded payload, signed checksums, release workflow, size budget |
| 5 Updater | Signed in-place update with self-test and rollback |
| 6 Docs + v0.1.0 | Client setup guides, troubleshooting, first stable release |

All phases are done. Each phase, its checks, and every deviation from the plan are recorded in the [execution log](prompts/2026.11.18_unattended_execution/2026.11.18_execution_log.md).

## Development

All development runs inside the dev container (see [.devcontainer/README.md](.devcontainer/README.md)); nothing is installed on the host computer. Inside the container:

```bash
uv sync --all-groups
uv run ruff check
uv run ruff format --check
uv run mypy src
uv run pytest
uv build            # wheel and source distribution in dist/

uv run mcp-siigo-unofficial              # tray app (needs a desktop)
uv run mcp-siigo-unofficial --stdio      # MCP over stdio
uv run mcp-siigo-unofficial --selftest   # check Qt, the vault, MCP, and HTTPS
```

Note: Qt for Linux on ARM (the dev container on Apple Silicon) is pinned to PySide6-Essentials 6.8.0.2, the last release with wheels for glibc 2.35. Releases use 6.11 on Windows, macOS, and Ubuntu x64.

## How this project is built: AI orchestration

This project is planned and built by AI agents (Claude Code) under the owner's direction. Every owner prompt is saved verbatim, together with its refined versions and the approved plan, in the [prompts/](prompts/) folder. The approved plan is [refined project inception v8](prompts/2026.11.18_project_inception/2026.11.18_refined_project_inception_v8.md), and the rules for every AI session are in [CLAUDE.md](CLAUDE.md).

---

## Español

> **Descarga:** [última versión](https://github.com/neyron1002/mcp-siigo-unofficial/releases/latest) para Windows, macOS y Ubuntu. Empiece con la [guía de instalación](docs/install.md#español).

**MCP Siigo Unofficial** conecta asistentes de IA como Claude, Codex, Copilot y Gemini con los datos contables de Siigo. Lo construí para la empresa de un amigo y para quien lo necesite: empresarios, contadores y profesionales contables. Es gratuito.

**Juan Manuel Pedraza**, ingeniero de sistemas en Bogotá, Colombia, con 16 años de experiencia. Soy desarrollador full stack, Forward Deployed Engineer y AI Builder.

¿Necesita una automatización con IA hecha a la medida de su empresa? ¿Quiere que un profesional lo acompañe a incorporar la IA en los procesos de su empresa? [Contácteme por LinkedIn](https://www.linkedin.com/in/juanpedraza1002/).

No está afiliado a Siigo S.A.S. Gratuito, "tal cual", sin garantía. Licencia MIT. Este MCP es solo un puente hacia la API de Siigo: usted es responsable de las acciones que su cliente de IA ejecute con él, y el autor no responde por las decisiones ni ejecuciones de la IA.

### Aviso y responsabilidad

- MCP significa Model Context Protocol, el estándar abierto que permite a los asistentes de IA usar herramientas externas.
- Siigo es una marca de Siigo S.A.S. Este proyecto **no** está afiliado, respaldado ni soportado por Siigo S.A.S.
- Las acciones de escritura (crear clientes, facturas y otros registros) crean registros **reales** en Siigo, y las facturas se envían a la DIAN. Están **apagadas por defecto**, se apagan de nuevo cada vez que la aplicación se reinicia, y cada escritura necesita su aprobación explícita.
- Usted es el único responsable de cada acción que su cliente de IA ejecute a través de este servidor MCP.

### Qué hace

Un solo archivo descargable por sistema operativo (Windows, macOS y Ubuntu) que se instala en su carpeta de usuario, sin permisos de administrador, y funciona como aplicación en la bandeja del sistema:

- Un servidor MCP local con 45 herramientas de lectura de Siigo (catálogos, clientes, productos, facturas, notas crédito, recibos de caja, comprobantes e informes).
- 9 herramientas de escritura detrás del interruptor **"Acciones de escritura"**: apagado por defecto, con advertencia, icono rojo mientras está activo, y su aprobación para cada escritura en la ventana de aprobación de la aplicación.
- Sus credenciales de Siigo se guardan cifradas en su equipo, y solo usted las escribe en la ventana de Configuración.
- Actualizaciones firmadas que preguntan antes de instalar, ejecutan una autoprueba y se revierten si falla.
- Inicio al encender el equipo, interfaz en español e inglés, y "Copiar configuración del cliente" para Claude Code, Claude Desktop, Codex, GitHub Copilot en VS Code y Gemini CLI ([guía de clientes](docs/clients.md#español)).

La documentación detallada está en inglés: [instalación](docs/install.md), [clientes](docs/clients.md), [uso](docs/usage.md), [herramientas](docs/tools.md) y [solución de problemas](docs/troubleshooting.md).

### Cómo se construye

Este proyecto lo planean y construyen agentes de IA (Claude Code) bajo la dirección del autor. Todas las instrucciones se guardan en la carpeta [prompts/](prompts/).
