# MCP Siigo Unofficial

## Download

| System | Download (newest version) |
|---|---|
| Windows 10/11 (x64) | [Download for Windows](https://github.com/neyron1002/mcp-siigo-unofficial/releases/latest/download/MCPSiigoUnofficial-windows-x64.exe) |
| macOS 13 or later (Apple silicon: M1 to M4) | [Download for Mac](https://github.com/neyron1002/mcp-siigo-unofficial/releases/latest/download/MCPSiigoUnofficial-macos-arm64.dmg) |
| Ubuntu 22.04/24.04 (x64) | [Download for Ubuntu](https://github.com/neyron1002/mcp-siigo-unofficial/releases/latest/download/mcp-siigo-unofficial-linux-x64) |

Then follow the [install guide](docs/install.md). Older versions and checksums are on the [releases page](https://github.com/neyron1002/mcp-siigo-unofficial/releases).

> [!WARNING]
> **New in v0.3.0: the whole Siigo API.** This version adds 22 write tools: quotations, purchase invoices, support documents, payment receipts, inventory categories, invoice edit, delete, and annul, invoice email, and webhooks ([list](docs/tools.md)). They follow Siigo's documentation of 2026-11-27, but they have **not been tested on a real Siigo company yet**.
>
> - Try them first with test records, or with records you can delete or correct, before you use them on real accounting data.
> - Read the approval window carefully before you approve. Deleting and annulling can't be undone, and electronic invoices go to the DIAN.
> - If something fails, or Siigo answers differently than expected, [report it on GitHub](https://github.com/neyron1002/mcp-siigo-unofficial/issues) with the tool name, what you asked for, and Siigo's error message (never your credentials or access key). I'll fix it.
> - Reading data works as before.

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

- A local MCP server (Streamable HTTP on `127.0.0.1` with a private bearer key, plus a `--stdio` mode) with 45 read tools for Siigo catalogs, customers, products, invoices, quotations, credit notes, purchase invoices, support documents, cash and payment receipts, journals, webhooks, and reports. See [MCP tools](docs/tools.md).
- 31 write tools that cover the rest of the Siigo API (create, update, delete, annul, invoice email, and webhooks) behind a **"Write actions" switch**, with a warning dialog, a red tray badge while enabled, and your approval of every write, in the mode you choose: the app's own approval window (default), a notification that opens it, or the AI app's question. Optional "approve similar writes for 10 minutes", and a guarded automatic approval for 1 hour or the day. Deletes, annulments, emails, and webhooks are always approved one at a time, and deletes and annulments only in the app's window, which shows the record first. Invoices, credit notes, journals, and cash receipts have duplicate protection. See [Write actions](docs/usage.md#write-actions).
- Siigo credentials stored in an encrypted local vault (AES-256-GCM, with the master key in the operating-system keychain). Only you type them, in the Settings dialog.
- Signed updates (SHA-256 checksums signed with Ed25519) that ask before installing, run a self-test, and roll back if it fails.
- **One-click connection** to Claude Code, Claude Desktop, Codex, Gemini CLI, and GitHub Copilot in VS Code: the app finds them and adds the Siigo tools for every project and session of your user (stdio by default, HTTP as an option), with backups, a conflict check, Disconnect, and automatic repair if the app moves. See [Client setup](docs/clients.md).
- Start at login, English and Spanish interface, and "Copy client setup" for manual setup.

## Documentation

| Guide | Contents |
|---|---|
| [Install](docs/install.md) | Download, first run on each system, Siigo API credentials, verify a download, uninstall |
| [Client setup](docs/clients.md) | One-click connection, stdio or HTTP, manual setup for Claude Code, Claude Desktop, Codex, GitHub Copilot in VS Code, Gemini CLI |
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
| Write approval (v0.1.1, v0.1.2) | The Siigo approval window, approve similar writes for 10 minutes, approval modes, guarded automatic approval |
| 7 One-click installer | Find AI apps, connect (stdio or HTTP), disconnect, repair, shared Siigo token |
| 8 Connect window | Connect AI apps window, tray AI apps menu, new-app notifications, Restart Claude Desktop |
| 9 Docs + v0.2.0 | One-click guides and the v0.2.0 release |
| New icon (v0.2.0) | A cloud with an arch bridge made of the letters "ii" |
| 10 Catalog refresh (v0.2.1-rc.1) | Tool schemas follow the Siigo docs of 2026-11-27 (health sector, Combo products, cash receipts), duplicate protection, catalog source in the repository |
| 11–15 Full API coverage (v0.3.0) | Risk levels in the approval flow (deletes, annulments, emails, and webhooks are approved one at a time), then 22 new write tools: quotations, purchase invoices, support documents, payment receipts, inventory categories, invoice edit, annul, delete, and email, and webhooks |

Each phase, its checks, and every deviation from the plan are recorded in the execution logs: [phases 0–6](prompts/2026.11.18_unattended_execution/2026.11.18_execution_log.md), [write approval](prompts/2026.11.19_write_approval_bug/2026.11.19_execution_log.md), [one-click connection](prompts/2026.11.19_one_click_client_install/2026.11.19_execution_log.md), and [API coverage](prompts/2026.11.27_api_coverage/2026.11.27_execution_log.md).

## Development

All development runs inside the dev container (see [.devcontainer/README.md](.devcontainer/README.md)); nothing is installed on the host computer. Inside the container:

```bash
uv sync --all-groups
uv run ruff check
uv run ruff format --check
uv run mypy src
uv run pytest
uv build            # wheel and source distribution in dist/
uv run python scripts/build_catalog.py   # rebuild catalog.json after editing scripts/catalog/endpoints.yaml

uv run mcp-siigo-unofficial              # tray app (needs a desktop)
uv run mcp-siigo-unofficial --stdio      # MCP over stdio
uv run mcp-siigo-unofficial --selftest   # check Qt, the vault, MCP, and HTTPS
```

Note: Qt for Linux on ARM (the dev container on Apple Silicon) is pinned to PySide6-Essentials 6.8.0.2, the last release with wheels for glibc 2.35. Releases use 6.11 on Windows, macOS, and Ubuntu x64.

## How this project is built: AI orchestration

This project is planned and built by AI agents (Claude Code) under the owner's direction. Every owner prompt is saved verbatim, together with its refined versions and the approved plan, in the [prompts/](prompts/) folder. The approved plan is [refined project inception v8](prompts/2026.11.18_project_inception/2026.11.18_refined_project_inception_v8.md), and the rules for every AI session are in [CLAUDE.md](CLAUDE.md).

---

## Español

### Descarga

| Sistema | Descarga (versión más reciente) |
|---|---|
| Windows 10/11 (x64) | [Descargar para Windows](https://github.com/neyron1002/mcp-siigo-unofficial/releases/latest/download/MCPSiigoUnofficial-windows-x64.exe) |
| macOS 13 o posterior (Apple silicon: M1 a M4) | [Descargar para Mac](https://github.com/neyron1002/mcp-siigo-unofficial/releases/latest/download/MCPSiigoUnofficial-macos-arm64.dmg) |
| Ubuntu 22.04/24.04 (x64) | [Descargar para Ubuntu](https://github.com/neyron1002/mcp-siigo-unofficial/releases/latest/download/mcp-siigo-unofficial-linux-x64) |

Luego siga la [guía de instalación](docs/install.md#español). Las versiones anteriores y las sumas de verificación están en la [página de versiones](https://github.com/neyron1002/mcp-siigo-unofficial/releases).

> [!WARNING]
> **Novedad en v0.3.0: toda la API de Siigo.** Esta versión agrega 22 herramientas de escritura: cotizaciones, facturas de compra, documentos soporte, recibos de pago, categorías de inventario, edición, borrado y anulación de facturas, envío de facturas por correo y webhooks ([lista](docs/tools.md)). Siguen la documentación de Siigo del 2026-11-27, pero **todavía no se han probado en una empresa real de Siigo**.
>
> - Pruébelas primero con registros de prueba, o con registros que pueda borrar o corregir, antes de usarlas con datos contables reales.
> - Lea con cuidado la ventana de aprobación antes de aprobar. Borrar y anular no se puede deshacer, y las facturas electrónicas van a la DIAN.
> - Si algo falla, o Siigo responde distinto de lo esperado, [repórtelo en GitHub](https://github.com/neyron1002/mcp-siigo-unofficial/issues) con el nombre de la herramienta, lo que pidió y el mensaje de error de Siigo (nunca sus credenciales ni su clave de acceso). Yo lo corrijo.
> - La lectura de datos funciona igual que antes.

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

- Un servidor MCP local con 45 herramientas de lectura de Siigo (catálogos, clientes, productos, facturas, cotizaciones, notas crédito, facturas de compra, documentos soporte, recibos de caja y de pago, comprobantes, webhooks e informes).
- 31 herramientas de escritura que cubren el resto de la API de Siigo (crear, actualizar, borrar, anular, enviar facturas por correo y webhooks) detrás del interruptor **"Acciones de escritura"**: apagado por defecto, con advertencia, icono rojo mientras está activo, y su aprobación para cada escritura en la ventana de aprobación de la aplicación. Borrar, anular, enviar correos y crear webhooks se aprueba siempre uno por uno; borrar y anular, solo en la ventana de la aplicación, que muestra primero el registro. Las facturas, notas crédito, comprobantes y recibos de caja tienen protección contra duplicados.
- Sus credenciales de Siigo se guardan cifradas en su equipo, y solo usted las escribe en la ventana de Configuración.
- Actualizaciones firmadas que preguntan antes de instalar, ejecutan una autoprueba y se revierten si falla.
- **Conexión con un clic** a Claude Code, Claude Desktop, Codex, Gemini CLI y GitHub Copilot en VS Code: la aplicación las encuentra y agrega las herramientas de Siigo para todos los proyectos y sesiones de su usuario, con copia de respaldo, sin tocar sus otros servidores, y con opción de desconectar ([guía de clientes](docs/clients.md#español)).
- Inicio al encender el equipo, interfaz en español e inglés, y "Copiar configuración del cliente" para la configuración manual.

La documentación detallada está en inglés: [instalación](docs/install.md), [clientes](docs/clients.md), [uso](docs/usage.md), [herramientas](docs/tools.md) y [solución de problemas](docs/troubleshooting.md).

### Cómo se construye

Este proyecto lo planean y construyen agentes de IA (Claude Code) bajo la dirección del autor. Todas las instrucciones se guardan en la carpeta [prompts/](prompts/).
