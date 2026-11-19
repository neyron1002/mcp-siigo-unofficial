"""English and Spanish UI strings (plan D17). The language follows the operating system,
unless the user picks one in Settings."""

from __future__ import annotations

import locale
import os
from typing import Literal

Language = Literal["en", "es"]
LANGUAGES: tuple[Language, ...] = ("en", "es")
SETTING_LANGUAGE = "ui.language"

LINKEDIN_URL = "https://www.linkedin.com/in/juanpedraza1002/"
WEBSITE_URL = "https://juanpedraza1002.com"
REPOSITORY_URL = "https://github.com/neyron1002/mcp-siigo-unofficial"
RELEASES_URL = REPOSITORY_URL + "/releases"

_STRINGS: dict[str, dict[Language, str]] = {
    "app.name": {"en": "MCP Siigo Unofficial", "es": "MCP Siigo Unofficial"},
    # Tray
    "tray.status.running": {
        "en": "MCP server running at {url}",
        "es": "Servidor MCP activo en {url}",
    },
    "tray.status.stopped": {
        "en": "MCP server stopped: {error}",
        "es": "Servidor MCP detenido: {error}",
    },
    "tray.status.no_credentials": {
        "en": "Siigo credentials missing: open Settings",
        "es": "Faltan las credenciales de Siigo: abra Configuración",
    },
    "tray.write.on": {"en": "Write actions: ON", "es": "Acciones de escritura: ACTIVADAS"},
    "tray.write.off": {"en": "Write actions: OFF", "es": "Acciones de escritura: DESACTIVADAS"},
    "tray.copy_setup": {"en": "Copy client setup", "es": "Copiar configuración del cliente"},
    "tray.settings": {"en": "Settings…", "es": "Configuración…"},
    "tray.autostart": {"en": "Start at login", "es": "Iniciar al encender el equipo"},
    "tray.updates": {"en": "Check for updates", "es": "Buscar actualizaciones"},
    "tray.about": {"en": "About", "es": "Acerca de"},
    "tray.quit": {"en": "Quit", "es": "Salir"},
    "tray.tooltip": {"en": "MCP Siigo Unofficial", "es": "MCP Siigo Unofficial"},
    "tray.tooltip.write": {
        "en": "MCP Siigo Unofficial — WRITE ACTIONS ENABLED",
        "es": "MCP Siigo Unofficial — ACCIONES DE ESCRITURA ACTIVADAS",
    },
    "notify.write.on.title": {"en": "Write actions enabled", "es": "Escritura activada"},
    "notify.write.on.body": {
        "en": "AI clients can now create and change real data in Siigo, with your approval.",
        "es": (
            "Los clientes de IA ya pueden crear y modificar datos reales en Siigo, "
            "con su aprobación."
        ),
    },
    "notify.write.off.title": {"en": "Write actions disabled", "es": "Escritura desactivada"},
    "notify.write.off.body": {
        "en": "AI clients can only read data from Siigo.",
        "es": "Los clientes de IA solo pueden leer datos de Siigo.",
    },
    "notify.copied.title": {"en": "Copied", "es": "Copiado"},
    "notify.copied.body": {
        "en": "The {client} setup is on the clipboard. It contains your private server key.",
        "es": (
            "La configuración para {client} está en el portapapeles. "
            "Contiene su clave privada del servidor."
        ),
    },
    "notify.already_running": {
        "en": "MCP Siigo Unofficial is already running. Look for its icon in the tray.",
        "es": "MCP Siigo Unofficial ya está abierto. Busque su icono en la bandeja del sistema.",
    },
    # Updates
    "update.latest": {
        "en": "You have the latest version ({version}).",
        "es": "Tiene la última versión ({version}).",
    },
    "update.available.title": {"en": "Update available", "es": "Actualización disponible"},
    "update.available.body": {
        "en": 'Version {version} is available. Use "Check for updates" to install it.',
        "es": 'La versión {version} está disponible. Use "Buscar actualizaciones" para instalarla.',
    },
    "update.ask": {
        "en": (
            "Version {version} is available (you have {current}).\n\n"
            "Download and install it now? The app restarts, and write actions stay off."
        ),
        "es": (
            "La versión {version} está disponible (usted tiene la {current}).\n\n"
            "¿Descargarla e instalarla ahora? La aplicación se reinicia y la escritura "
            "queda desactivada."
        ),
    },
    "update.manual": {
        "en": (
            "Version {version} is available. This copy cannot update itself; "
            "download it from the releases page."
        ),
        "es": (
            "La versión {version} está disponible. Esta copia no se actualiza sola; "
            "descárguela de la página de versiones."
        ),
    },
    "update.downloading": {
        "en": "Downloading version {version} and checking its signature…",
        "es": "Descargando la versión {version} y verificando su firma…",
    },
    "update.error": {
        "en": "The update did not complete: {error}",
        "es": "La actualización no terminó: {error}",
    },
    "update.done.title": {"en": "Updated", "es": "Actualizado"},
    "update.done.body": {
        "en": "MCP Siigo Unofficial was updated from {old} to {new}.",
        "es": "MCP Siigo Unofficial se actualizó de la {old} a la {new}.",
    },
    "update.rollback.title": {"en": "Update rolled back", "es": "Actualización revertida"},
    "update.rollback.body": {
        "en": "Version {new} did not pass its self-test, so {old} was kept.",
        "es": "La versión {new} no pasó su autoprueba; se mantuvo la {old}.",
    },
    "mac.move_to_apps": {
        "en": ("Drag MCP Siigo Unofficial to the Applications folder, then open it from there."),
        "es": ("Arrastre MCP Siigo Unofficial a la carpeta Aplicaciones y ábralo desde allí."),
    },
    # Write actions dialog
    "write.title": {"en": "Enable write actions?", "es": "¿Activar las acciones de escritura?"},
    "write.body": {
        "en": (
            "<p><b>Write actions create and change REAL records in your Siigo company.</b> "
            "Electronic invoices are sent to the DIAN (Colombia's tax authority) and cannot "
            "simply be deleted.</p>"
            "<p>This MCP is only a bridge to the Siigo API. <b>You are fully responsible for "
            "every action your AI client executes with it.</b> The software is free, provided "
            '"as is", without warranty, and its author is not responsible for AI decisions '
            "or executions.</p>"
            "<p>Every write will still ask for your approval. Write actions turn off again "
            "when the app restarts.</p>"
        ),
        "es": (
            "<p><b>Las acciones de escritura crean y modifican registros REALES en su empresa "
            "en Siigo.</b> Las facturas electrónicas se envían a la DIAN y no se pueden borrar "
            "sin más.</p>"
            "<p>Este MCP es solo un puente hacia la API de Siigo. <b>Usted es el único "
            "responsable de cada acción que su cliente de IA ejecute con él.</b> El software es "
            'gratuito, se entrega "tal cual", sin garantía, y su autor no responde por las '
            "decisiones ni ejecuciones de la IA.</p>"
            "<p>Cada escritura le pedirá su aprobación. Las acciones de escritura se desactivan "
            "de nuevo al reiniciar la aplicación.</p>"
        ),
    },
    "write.accept": {
        "en": "I understand and accept responsibility",
        "es": "Entiendo y acepto la responsabilidad",
    },
    "write.enable": {"en": "Enable write actions", "es": "Activar acciones de escritura"},
    "write.cancel": {"en": "Cancel", "es": "Cancelar"},
    # Settings dialog
    "settings.title": {"en": "Settings", "es": "Configuración"},
    "settings.siigo": {"en": "Siigo API credentials", "es": "Credenciales de la API de Siigo"},
    "settings.help": {
        "en": "In Siigo Nube: Alianzas → Mi Credencial API.",
        "es": "En Siigo Nube: Alianzas → Mi Credencial API.",
    },
    "settings.username": {"en": "API username", "es": "Usuario de la API"},
    "settings.access_key": {"en": "Access key", "es": "Access key"},
    "settings.access_key.saved": {
        "en": "Saved (leave empty to keep it)",
        "es": "Guardada (deje vacío para conservarla)",
    },
    "settings.partner_id": {"en": "Partner-Id", "es": "Partner-Id"},
    "settings.language": {"en": "Language", "es": "Idioma"},
    "settings.language.system": {"en": "System", "es": "Sistema"},
    "settings.port": {"en": "Local MCP port", "es": "Puerto MCP local"},
    "settings.write": {"en": "Write actions", "es": "Acciones de escritura"},
    "settings.test": {"en": "Test connection", "es": "Probar conexión"},
    "settings.test.running": {"en": "Testing…", "es": "Probando…"},
    "settings.test.ok": {"en": "Connected to Siigo.", "es": "Conexión con Siigo correcta."},
    "settings.test.fail": {"en": "Siigo error: {error}", "es": "Error de Siigo: {error}"},
    "settings.clear": {"en": "Delete credentials", "es": "Borrar credenciales"},
    "settings.save": {"en": "Save", "es": "Guardar"},
    "settings.cancel": {"en": "Cancel", "es": "Cancelar"},
    "settings.error.username": {
        "en": "Enter the API username.",
        "es": "Escriba el usuario de la API.",
    },
    "settings.error.access_key": {"en": "Enter the access key.", "es": "Escriba la access key."},
    "settings.error.partner_id": {
        "en": "Partner-Id must be 3 to 100 letters or digits, with no spaces.",
        "es": "El Partner-Id debe tener de 3 a 100 letras o números, sin espacios.",
    },
    "settings.restart": {
        "en": "The new port is used after the app restarts.",
        "es": "El nuevo puerto se usa al reiniciar la aplicación.",
    },
    # About dialog
    "about.title": {"en": "About MCP Siigo Unofficial", "es": "Acerca de MCP Siigo Unofficial"},
    "about.version": {"en": "Version {version}", "es": "Versión {version}"},
    "about.body": {
        "en": (
            "<p><b>MCP Siigo Unofficial</b> connects AI assistants such as Claude, Codex, "
            "Copilot, and Gemini to your Siigo accounting data. I built it for a friend's "
            "company, and for anyone who needs it: business owners, accountants, and "
            "accounting professionals. It is free of charge.</p>"
            "<p><b>Juan Manuel Pedraza</b>, a systems engineer from Bogotá, Colombia, with 16 "
            "years of experience. I am a full-stack developer, Forward Deployed Engineer, and "
            "AI Builder.</p>"
            "<p>Do you need an AI automation built for your company's specific needs? Do you "
            "want a professional to guide you as you bring AI into your company's processes? "
            "Contact me on LinkedIn.</p>"
            '<p><small>Not affiliated with Siigo S.A.S. Free, provided "as is", without '
            "warranty. MIT License. This MCP is only a bridge to the Siigo API: you are "
            "responsible for the actions your AI client executes with it, and the author is "
            "not responsible for AI decisions or executions.</small></p>"
        ),
        "es": (
            "<p><b>MCP Siigo Unofficial</b> conecta asistentes de IA como Claude, Codex, "
            "Copilot y Gemini con los datos contables de Siigo. Lo construí para la empresa de "
            "un amigo y para quien lo necesite: empresarios, contadores y profesionales "
            "contables. Es gratuito.</p>"
            "<p><b>Juan Manuel Pedraza</b>, ingeniero de sistemas en Bogotá, Colombia, con 16 "
            "años de experiencia. Soy desarrollador full stack, Forward Deployed Engineer y "
            "AI Builder.</p>"
            "<p>¿Necesita una automatización con IA hecha a la medida de su empresa? ¿Quiere "
            "que un profesional lo acompañe a incorporar la IA en los procesos de su empresa? "
            "Contácteme por LinkedIn.</p>"
            '<p><small>No está afiliado a Siigo S.A.S. Gratuito, "tal cual", sin garantía. '
            "Licencia MIT. Este MCP es solo un puente hacia la API de Siigo: usted es "
            "responsable de las acciones que su cliente de IA ejecute con él, y el autor no "
            "responde por las decisiones ni ejecuciones de la IA.</small></p>"
        ),
    },
    "about.linkedin": {"en": "Contact me on LinkedIn", "es": "Contácteme por LinkedIn"},
    "about.website": {"en": "Website", "es": "Sitio web"},
    "about.source": {"en": "Source code", "es": "Código fuente"},
    "about.close": {"en": "Close", "es": "Cerrar"},
    # Write approval window (plan section 5.1, 2026-11-19)
    "approval.window_title": {
        "en": "Approve a write in Siigo",
        "es": "Aprobar una escritura en Siigo",
    },
    "approval.headline": {
        "en": "{client} wants to run: {title}",
        "es": "{client} quiere ejecutar: {title}",
    },
    "approval.warning": {
        "en": "This creates or changes REAL data in your Siigo company (invoices go to "
        "the DIAN). Nothing is sent unless you approve.",
        "es": "Esto crea o cambia datos REALES en su empresa de Siigo (las facturas van a "
        "la DIAN). No se envía nada si usted no aprueba.",
    },
    "approval.field.action": {"en": "Action", "es": "Acción"},
    "approval.field.request": {"en": "Request", "es": "Petición"},
    "approval.field.client": {"en": "Asked by", "es": "Solicitado por"},
    "approval.details.show": {"en": "Show details", "es": "Mostrar detalles"},
    "approval.details.hide": {"en": "Hide details", "es": "Ocultar detalles"},
    "approval.countdown": {
        "en": "Closes in {time} (rejected if nobody answers)",
        "es": "Se cierra en {time} (se rechaza si nadie responde)",
    },
    "approval.approve": {"en": "Approve", "es": "Aprobar"},
    "approval.reject": {"en": "Reject", "es": "Rechazar"},
    "approval.approve_similar": {
        "en": "Approve similar writes for 10 minutes",
        "es": "Aprobar escrituras similares por 10 minutos",
    },
    "approval.similar_hint": {
        "en": "Similar = the same action ({title}) from the same AI app connection.",
        "es": "Similar = la misma acción ({title}) desde la misma conexión de la app de IA.",
    },
    "notify.approval.title": {"en": "Approval needed", "es": "Se necesita aprobación"},
    "notify.approval.body": {
        "en": "{client} wants to run {title} in Siigo. Open the window to approve or reject.",
        "es": "{client} quiere ejecutar {title} en Siigo. Abra la ventana para aprobar o rechazar.",
    },
    "tray.grants": {
        "en": "Similar writes approved: {title} ({minutes} min left)",
        "es": "Escrituras similares aprobadas: {title} (quedan {minutes} min)",
    },
    "tray.grants.stop": {
        "en": "Stop approving similar writes now",
        "es": "Dejar de aprobar escrituras similares ahora",
    },
    "settings.approval": {"en": "Write approval", "es": "Aprobación de escrituras"},
    "settings.approval.siigo_window": {
        "en": "Siigo window for every write (recommended)",
        "es": "Ventana de Siigo para cada escritura (recomendado)",
    },
    "settings.approval.notification": {
        "en": "Notification first (the window opens on click, or after 15 s)",
        "es": "Primero una notificación (la ventana abre al hacer clic, o a los 15 s)",
    },
    "settings.approval.ai_app": {
        "en": "In the AI app (its own question; the Siigo window if it can't ask)",
        "es": "En la app de IA (su propia pregunta; la ventana de Siigo si no puede)",
    },
    "tray.auto": {
        "en": "Approve all writes automatically",
        "es": "Aprobar todas las escrituras automáticamente",
    },
    "tray.auto.hour": {"en": "For 1 hour…", "es": "Por 1 hora…"},
    "tray.auto.today": {"en": "Until the end of today…", "es": "Hasta el final de hoy…"},
    "tray.auto.active": {
        "en": "AUTOMATIC APPROVAL: {minutes} min, {writes} writes left",
        "es": "APROBACIÓN AUTOMÁTICA: quedan {minutes} min y {writes} escrituras",
    },
    "tray.auto.stop": {
        "en": "Stop automatic approval now",
        "es": "Detener la aprobación automática ahora",
    },
    "tray.tooltip.auto": {
        "en": "MCP Siigo Unofficial — AUTOMATIC APPROVAL OF WRITES",
        "es": "MCP Siigo Unofficial — APROBACIÓN AUTOMÁTICA DE ESCRITURAS",
    },
    "auto.title": {"en": "Automatic approval", "es": "Aprobación automática"},
    "auto.body": {
        "en": "<b>Dangerous.</b> Every write from every AI app runs in your Siigo company "
        "<b>without asking you</b>, {span}, up to {max} writes. Invoices go to the DIAN. "
        "A mistake, or hidden instructions in your data (prompt injection), can create or "
        "change many real records. It stops at the time limit, after {max} writes, when "
        "write actions turn off, when the app restarts, or with Stop now. Every write is "
        "logged.<br><br>To turn it on, type <b>{text}</b>:",
        "es": "<b>Peligroso.</b> Cada escritura de cualquier app de IA se ejecuta en su "
        "empresa de Siigo <b>sin preguntarle</b>, {span}, hasta {max} escrituras. Las "
        "facturas van a la DIAN. Un error, o instrucciones ocultas en sus datos (inyección "
        "de instrucciones), pueden crear o cambiar muchos registros reales. Se detiene al "
        "terminar el tiempo, tras {max} escrituras, al apagar las acciones de escritura, al "
        "reiniciar la aplicación, o con Detener ahora. Cada escritura queda registrada."
        "<br><br>Para activarla, escriba <b>{text}</b>:",
    },
    "auto.span.hour": {"en": "for 1 hour", "es": "durante 1 hora"},
    "auto.span.today": {"en": "until the end of today", "es": "hasta el final de hoy"},
    "auto.enable": {"en": "Turn on automatic approval", "es": "Activar aprobación automática"},
    "auto.cancel": {"en": "Cancel", "es": "Cancelar"},
    "notify.auto.on.title": {
        "en": "Automatic approval is ON",
        "es": "La aprobación automática está ACTIVADA",
    },
    "notify.auto.on.body": {
        "en": "Writes run without asking, {span}. Stop it from the tray menu.",
        "es": "Las escrituras se ejecutan sin preguntar, {span}. Deténgala desde el menú.",
    },
    "notify.auto.off.title": {
        "en": "Automatic approval ended",
        "es": "La aprobación automática terminó",
    },
    "notify.auto.off.body": {
        "en": "Writes need your approval again.",
        "es": "Las escrituras necesitan su aprobación de nuevo.",
    },
    "notify.grant.title": {
        "en": "Similar writes approved for 10 minutes",
        "es": "Escrituras similares aprobadas por 10 minutos",
    },
    "notify.grant.body": {
        "en": "{title} from the same AI app runs without asking until the time ends. "
        "Use the tray menu to stop it now.",
        "es": "{title} desde la misma app de IA se ejecuta sin preguntar hasta que termine "
        "el tiempo. Use el menú del icono para detenerlo ahora.",
    },
}


def system_language() -> Language:
    """``es`` when the operating system language is Spanish, otherwise ``en``."""
    for name in ("LC_ALL", "LC_MESSAGES", "LANG", "LANGUAGE"):
        value = os.environ.get(name, "")
        if value and value not in {"C", "POSIX"} and not value.startswith("C."):
            return "es" if value.lower().startswith("es") else "en"
    try:
        code = locale.getlocale()[0] or ""
    except ValueError:
        code = ""
    return "es" if code.lower().startswith(("es", "spanish")) else "en"


class Translator:
    """Looks up UI strings in the current language."""

    def __init__(self, language: Language | None = None) -> None:
        self.language: Language = language or system_language()

    def set_language(self, language: Language | None) -> None:
        self.language = language or system_language()

    def __call__(self, key: str, **values: object) -> str:
        text = _STRINGS[key][self.language]
        return text.format(**values) if values else text


def all_keys() -> list[str]:
    return sorted(_STRINGS)


def text_for(key: str, language: Language) -> str:
    return _STRINGS[key][language]
