# MCP Siigo Unofficial

> **Status: in development.** There is no release yet. Phase 0 (foundation) is done; phase 1 (Siigo client and encrypted vault) is in progress.

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

## What it will be

A single downloadable file per operating system (Windows 10/11 x64, macOS 13+ arm64, Ubuntu 22.04/24.04 x64). It installs itself into your user folder with no administrator rights, and it runs as a tray app:

- A local MCP server (Streamable HTTP on `127.0.0.1` with a bearer key, plus a `--stdio` mode) with read tools for Siigo catalogs, customers, products, invoices, credit notes, cash receipts, and journals.
- Write tools behind a **"Write actions" switch**, with a warning dialog, a red tray badge while enabled, and per-write user approval (MCP elicitation, or a one-time confirmation code).
- Siigo credentials stored in an encrypted local vault (AES-256-GCM, with the master key in the operating-system keychain). Only you type them, in the Settings dialog.
- Signed automatic updates (SHA-256 checksums signed with Ed25519) that ask before installing.
- Start at login, English and Spanish interface, and "Copy client setup" for Claude Code, Claude Desktop, Codex, GitHub Copilot in VS Code, and Gemini CLI.

## Roadmap

| Phase | Output |
|---|---|
| 0 Foundation | Dev container, license, README, project tooling, CI on 3 operating systems, reference analysis |
| 1 Siigo client + vault | Authentication and token renewal, encrypted vault, mock Siigo server |
| 2 MCP server | HTTP + stdio, tool catalog, write switch gate, elicitation and two-step confirmation |
| 3 Tray + UI | Tray icon, Settings, About, English/Spanish, start at login, write-enable warning |
| 4 Single-file build | Launcher with embedded payload, signed checksums, release workflow, size budget |
| 5 Updater | In-place update with rollback |
| 6 Docs + v0.1.0 | Client setup guides, troubleshooting, first stable release |

## Development

All development runs inside the dev container (see [.devcontainer/README.md](.devcontainer/README.md)); nothing is installed on the host computer. Inside the container:

```bash
uv sync --all-groups
uv run ruff check
uv run ruff format --check
uv run mypy src
uv run pytest
uv build            # wheel and source distribution in dist/
```

## How this project is built: AI orchestration

This project is planned and built by AI agents (Claude Code) under the owner's direction. Every owner prompt is saved verbatim, together with its refined versions and the approved plan, in the [prompts/](prompts/) folder. The approved plan is [refined project inception v8](prompts/2026.11.18_project_inception/2026.11.18_refined_project_inception_v8.md), and the rules for every AI session are in [CLAUDE.md](CLAUDE.md).

---

## Español

> **Estado: en desarrollo.** Todavía no hay una versión publicada.

**MCP Siigo Unofficial** conecta asistentes de IA como Claude, Codex, Copilot y Gemini con los datos contables de Siigo. Lo construí para la empresa de un amigo y para quien lo necesite: empresarios, contadores y profesionales contables. Es gratuito.

**Juan Manuel Pedraza**, ingeniero de sistemas en Bogotá, Colombia, con 16 años de experiencia. Soy desarrollador full stack, Forward Deployed Engineer y AI Builder.

¿Necesita una automatización con IA hecha a la medida de su empresa? ¿Quiere que un profesional lo acompañe a incorporar la IA en los procesos de su empresa? [Contácteme por LinkedIn](https://www.linkedin.com/in/juanpedraza1002/).

No está afiliado a Siigo S.A.S. Gratuito, "tal cual", sin garantía. Licencia MIT. Este MCP es solo un puente hacia la API de Siigo: usted es responsable de las acciones que su cliente de IA ejecute con él, y el autor no responde por las decisiones ni ejecuciones de la IA.

### Aviso y responsabilidad

- MCP significa Model Context Protocol, el estándar abierto que permite a los asistentes de IA usar herramientas externas.
- Siigo es una marca de Siigo S.A.S. Este proyecto **no** está afiliado, respaldado ni soportado por Siigo S.A.S.
- Las acciones de escritura (crear clientes, facturas y otros registros) crean registros **reales** en Siigo, y las facturas se envían a la DIAN. Están **apagadas por defecto**, se apagan de nuevo cada vez que la aplicación se reinicia, y cada escritura necesita su aprobación explícita.
- Usted es el único responsable de cada acción que su cliente de IA ejecute a través de este servidor MCP.

### Qué será

Un solo archivo descargable por sistema operativo (Windows, macOS y Ubuntu) que se instala en su carpeta de usuario, sin permisos de administrador, y funciona como aplicación en la bandeja del sistema. Sus credenciales de Siigo se guardan cifradas en su equipo, y solo usted las escribe en la ventana de Configuración.

### Cómo se construye

Este proyecto lo planean y construyen agentes de IA (Claude Code) bajo la dirección del autor. Todas las instrucciones se guardan en la carpeta [prompts/](prompts/).
