# Reference analysis: the owner's first Siigo MCP server (`mcp_siigo`)

- Date: 2026-11-18 (phase 0)
- Plan: section 6 of [refined project inception v8](../prompts/2026.11.18_project_inception/2026.11.18_refined_project_inception_v8.md)
- Authorship: the owner, Juan Manuel Pedraza, confirmed on 2026-11-18 that he wrote `mcp_siigo` ([raw prompt](../prompts/2026.11.18_unattended_execution/2026.11.18_raw_reference_is_own_mcp.md)). Its code, endpoint catalog, and docs may be adapted into `src/` under this project's MIT license.
- Location: the owner keeps it locally in `references/existing_mcp/mcp_siigo/`. The `references/` folder is not part of the repository (it is ignored by git).

## 1. What `mcp_siigo` does

`mcp_siigo` is a Python MCP server (MCP means Model Context Protocol) for the Siigo Nube REST API (`https://api.siigo.com`). It depends on `mcp`, `httpx`, `pyyaml`, `pydantic-settings`, and `python-dotenv`.

| Area | How it works |
|---|---|
| Catalog-driven tools | `catalogo/endpoints.yaml` (about 7,600 lines) describes **78 endpoints** (45 read, 33 write) in 22 resources: method, path, path and query parameters, JSON body schema, examples, and notes. It is validated with pydantic models. The server generates one tool, `siigo_<name>`, per endpoint, with an input schema built from the catalog. A script (`scripts/generar_catalogo.py`) builds the catalog from the official API Blueprint (Apiary) file plus the developer portal pages, with a hand-reviewed table on top. |
| Fixed tools | `siigo_estado` (mode and settings without secrets), `siigo_listar_endpoints`, `siigo_buscar_documentacion`, and `siigo_llamar` (a generic call, under the same write guard). |
| Embedded docs | Siigo's official documentation is saved as Markdown (`docs/00`–`40`) and exposed as MCP resources (`siigo://docs`, `siigo://docs/{topic}`, `siigo://catalogo`), plus two prompts (consult products and prices, create an invoice). |
| Dry-run | Without credentials, or with `SIIGO_DRY_RUN=true`, no request leaves the machine. Every tool returns the request it would send plus the official example response. |
| Write guard | Write tools are registered only if they are listed in `SIIGO_HABILITAR_ESCRITURA` (or `*`). Even then, a call without `confirmar=true` returns only a preview (method, URL, query, body, and missing required fields). `siigo_llamar` blocks `/auth`. |
| Authentication | `POST /auth` with username and access key. The token is cached in memory and renewed 5 minutes before it expires (24 hours). `expires_in` is documented as milliseconds, but the value is seconds; the client handles both. |
| 401/429 handling | On 401 it authenticates again and retries once. On 429 it waits for `Retry-After` (at most 60 seconds) and retries once. Siigo errors (`Errors[].Code/Message/Params/Detail`) become a readable error object that points to the error-code docs. Timeout: 120 seconds, as Siigo recommends. |
| Partner-Id rules | The `Partner-Id` header is required on every call. It must be 3 to 100 alphanumeric characters, with no underscores or spaces (otherwise Siigo answers `invalid_partner_id`). Credentials come from Siigo Nube → *Alianzas* → *Mi Credencial API*. |
| Secrets in logs | The token and the access key are never returned or logged; `__repr__` hides them. |
| Transport | Streamable HTTP on `0.0.0.0:8002/mcp`, with the SDK's DNS-rebinding protection turned off, because it runs inside a container. |
| Tests | pytest for the catalog, the client (with `respx`, an httpx mocking library), and the server in memory. |

## 2. Ideas we adopt

1. **A declarative endpoint catalog** as the single source of truth for tools: names, parameters, body schemas, read or write, and the docs link. We validate it in tests (unique names, path parameters match the path, no GET is a write).
2. **The full documentation inside the server**, exposed as MCP resources, plus a documentation search tool, so the AI can read Siigo's rules before it calls a write tool.
3. **A preview before every write.** It becomes our two-step confirmation (plan section 5.1), with a server-side one-time `confirmation_id` instead of a `confirmar` flag that the model can set by itself.
4. **A dry-run / mock mode** that answers with the official example responses. It is the base of our mock Siigo server for tests (phase 1).
5. **Authentication details:** cache the token, renew it early, accept seconds or milliseconds for `expires_in`, re-authenticate once on 401, respect `Retry-After` on 429 with a cap, and use a 120-second timeout.
6. **Readable errors** that keep Siigo's error code, message, and parameters, plus a hint to the error-code docs.
7. **Partner-Id validation** (3–100 alphanumeric characters). It confirms that our default `MCPSiigoUnofficial` is valid (plan P6).
8. **A status tool** that reports the mode and the settings without secrets.

## 3. What we do differently

| Topic | `mcp_siigo` | MCP Siigo Unofficial | Why |
|---|---|---|---|
| Secrets | `.env` file and environment variables in plain text | Encrypted vault: SQLite, AES-256-GCM fields, master key in the OS keychain; typed only in the Settings dialog (D6, D7) | The users are business owners and accountants on their own computers, not a server operator. |
| Write enablement | A comma-separated list in an environment variable | A **"Write actions" switch** in the tray: off by default, off again after every restart, a warning dialog with an acceptance of responsibility, a red tray badge, and notifications (D15, P9) | A non-technical user must see clearly when writes are possible. |
| Write approval | `confirmar=true` argument, which the model can send by itself | MCP **elicitation** (the client asks the user directly) or a server-enforced one-time `confirmation_id` that expires after 5 minutes (P10) | The server must not depend on the model's good behavior. |
| Hidden write tools | Not registered when not enabled | Not listed while the switch is off, and the server sends `notifications/tools/list_changed` when the switch changes | Same idea, but it changes at run time. |
| Network binding | `0.0.0.0:8002`, DNS-rebinding protection off | `127.0.0.1` only, a random **bearer key**, and DNS-rebinding protection on; plus a `--stdio` mode (D4) | Other machines on the network must not reach the user's accounting data. |
| Runtime dependencies | `pyyaml`, `python-dotenv`, `pydantic-settings` shipped | Only `mcp`, `httpx`, `cryptography`, `keyring`, `platformdirs`, `PySide6-Essentials`. The catalog is converted to a Python/JSON module at build time (D20) | The smallest single-file build. |
| Docs size | All raw HTML and Markdown in the repository | Only the Markdown that tools need, compressed in the build; raw scraped files stay out of the release | D20. |
| Packaging | Run from source with `uv run` | One self-installing file per OS, with signed updates (D8, D10–D12) | Ease of use for non-developers. |
| Language | Spanish identifiers and messages | English code; English and Spanish UI (D17) | Public, international repository. |
