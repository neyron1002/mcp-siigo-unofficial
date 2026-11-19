# Install

MCP Siigo Unofficial is one file per operating system. It installs into your user folder, with no administrator rights, and runs as a tray app.

| System | File on the [releases page](https://github.com/neyron1002/mcp-siigo-unofficial/releases) |
|---|---|
| Windows 10/11 (x64) | `MCPSiigoUnofficial-<version>-windows-x64.exe` |
| macOS 13 or later (Apple silicon) | `MCPSiigoUnofficial-<version>-macos-arm64.dmg` |
| Ubuntu 22.04/24.04 (x64) | `mcp-siigo-unofficial-<version>-linux-x64` |

The files are not signed with a paid code-signing certificate, so each system warns you the first time. The steps below show how to continue. Each release also has `SHA256SUMS` and its Ed25519 signature `SHA256SUMS.sig`; see [Verify a download](#verify-a-download).

## Windows

1. Download the `.exe` file and double-click it.
2. If SmartScreen shows "Windows protected your PC", click **More info**, then **Run anyway**.
3. The app installs into `%LOCALAPPDATA%\MCPSiigoUnofficial\` and its icon appears in the tray (near the clock; open the `^` arrow if you don't see it).

## macOS

1. Download the `.dmg` file and open it.
2. Drag **MCP Siigo Unofficial** to the **Applications** folder. Start at login needs the app in Applications, so the app asks you to move it if you open it from the DMG.
3. Open the app from Applications. If macOS says it cannot verify the developer, open **System Settings → Privacy & Security**, find the message about MCP Siigo Unofficial, and click **Open Anyway**.
4. The icon appears in the menu bar. The app has no Dock icon.

## Ubuntu

1. Download the file.
2. Browsers remove the "executable" permission. Right-click the file, choose **Properties**, and turn on **Executable as Program**. In a terminal, you can run `chmod +x mcp-siigo-unofficial-*-linux-x64` instead.
3. Double-click the file (or run it in a terminal).
4. The icon appears in the top bar. On Ubuntu's default desktop this needs the "AppIndicator and KStatusNotifierItem Support" extension, which Ubuntu turns on by default. Without a tray, the Settings window opens instead, and closing it quits the app.

## First run

1. Find your Siigo API credentials: in Siigo Nube, open **Alianzas → Mi Credencial API**. You need the **API username** (an email) and the **access key**.
2. The Settings window opens on the first run. Type the API username and the access key, click **Test connection**, then **Save**. Only you type them; they are stored encrypted on your computer (see [Where your data is](usage.md#where-your-data-is)).
3. **Partner-Id** is a name that identifies this app to Siigo. Keep the default `MCPSiigoUnofficial` unless Siigo gives you another one (3 to 100 letters and numbers).
4. Connect your AI apps: the **Connect your AI apps** window opens when an AI app (Claude Code, Claude Desktop, Codex, Gemini CLI, or VS Code) is installed. Click **Connect**. You can open it later from the tray menu: **AI apps ▸ Connect AI apps…**. See [Client setup](clients.md).

Start at login is turned on after the first run. You can turn it off in the tray menu.

## Verify a download

You can check that a file is the one published by the author:

1. Download the file, `SHA256SUMS`, and `SHA256SUMS.sig` from the same release.
2. Check the SHA-256: on Windows, `certutil -hashfile <file> SHA256`; on macOS, `shasum -a 256 <file>`; on Ubuntu, `sha256sum <file>`. The result must match the line for that file in `SHA256SUMS`.
3. The signature in `SHA256SUMS.sig` is checked against the public key in [`release_public_key.pem`](../src/mcp_siigo_unofficial/update/release_public_key.pem). The app's updater does this automatically; from a copy of the repository you can run `uv run python packaging/sign.py verify <folder> --present-only`.

## Uninstall

Uninstalling with `--uninstall` first removes the Siigo entries this app added to your AI apps.

- **Windows:** quit the app from the tray menu, then run `%LOCALAPPDATA%\MCPSiigoUnofficial\launcher.exe --uninstall`. Add `--purge-data` to also delete your encrypted vault (credentials and settings) and its keychain key.
- **Ubuntu:** quit the app, then run `~/.local/share/mcp-siigo-unofficial/launcher --uninstall` (add `--purge-data` to delete your data too).
- **macOS:** quit the app. To remove the Siigo entries from your AI apps, first run `"/Applications/MCP Siigo Unofficial.app/Contents/MacOS/MCPSiigoUnofficial" --disconnect-clients`. To delete your data, run `"/Applications/MCP Siigo Unofficial.app/Contents/MacOS/MCPSiigoUnofficial" --purge-data`. Then drag the app from Applications to the Trash, and delete `~/Library/LaunchAgents/com.neyron1002.mcp-siigo-unofficial.plist` and the folder `~/Library/Application Support/MCPSiigoUnofficial`.

---

## Español

1. Descargue el archivo de su sistema desde la [página de versiones](https://github.com/neyron1002/mcp-siigo-unofficial/releases).
2. **Windows:** haga doble clic; si SmartScreen lo detiene, haga clic en **Más información → Ejecutar de todas formas**. **macOS:** abra el DMG, arrastre la aplicación a **Aplicaciones** y ábrala desde allí; si macOS la bloquea, use **Configuración del Sistema → Privacidad y seguridad → Abrir de todas formas**. **Ubuntu:** en **Propiedades**, active **Permitir ejecutar como programa** y haga doble clic.
3. En Siigo Nube, abra **Alianzas → Mi Credencial API** y copie el **usuario de la API** y la **access key**. Escríbalos en la ventana de Configuración, pruebe la conexión y guarde. Solo usted los escribe; se guardan cifrados en su equipo.
4. Conecte sus apps de IA: la ventana **Conectar sus apps de IA** se abre sola si tiene instalada una app de IA (Claude Code, Claude Desktop, Codex, Gemini CLI o VS Code). Haga clic en **Conectar**. Después puede abrirla desde el menú del icono: **Apps de IA ▸ Conectar apps de IA…** ([guía de clientes](clients.md#español)).
