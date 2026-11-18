"""Which Qt files the app ships (plan D20, section 3.2 item 1).

Used by the PySide6 hook overrides in ``packaging/hooks`` (so the dependencies of
dropped plugins are never collected) and by ``app.spec`` (a final pass).
"""

from __future__ import annotations

import re
from pathlib import PurePath

#: Qt libraries the app needs. XcbQpa/Wayland* back the Linux platform plugins.
QT_LIBS_KEEP = frozenset(
    {"Core", "Gui", "Widgets", "DBus", "XcbQpa", "WaylandClient", "WlShellIntegration"}
)
#: Qt for Python extension modules the app imports.
PYSIDE_MODULES_KEEP = frozenset({"Core", "Gui", "Widgets", "DBus"})
#: Plugin folders: platform integration and text input (accents and dead keys on Linux).
PLUGIN_DIRS_KEEP = frozenset(
    {"platforms", "platforminputcontexts", "wayland-shell-integration", "wayland-decoration-client"}
)
#: Platform plugins: one per system, plus offscreen for the headless --selftest.
PLATFORM_KEEP = re.compile(r"(qwindows|qcocoa|qxcb|qwayland-generic|qoffscreen)", re.IGNORECASE)
#: Wayland: the standard desktop shell protocol only.
WAYLAND_SHELL_KEEP = re.compile(r"xdg-shell", re.IGNORECASE)
TRANSLATIONS_KEEP = re.compile(r"^qtbase_(en|es)\.qm$", re.IGNORECASE)
_QT_LIB = re.compile(r"^(?:lib)?Qt6([A-Za-z]+?)(?:\.so[.\d]*|\.dll|\.dylib)?$")
_PYSIDE_MODULE = re.compile(r"^Qt([A-Za-z]+)\.(?:abi3\.so|pyd|so)$")


def keep(path: str) -> bool:
    """True if the file at ``path`` (source or destination) belongs in the bundle."""
    parts = PurePath(path.replace("\\", "/")).parts
    name = parts[-1] if parts else path
    posix = "/".join(parts)
    if "/plugins/" in posix or posix.startswith("plugins/"):
        plugin_dir = posix.split("plugins/", 1)[1].split("/", 1)[0]
        if plugin_dir not in PLUGIN_DIRS_KEEP:
            return False
        if plugin_dir == "platforms":
            return bool(PLATFORM_KEEP.search(name))
        if plugin_dir == "wayland-shell-integration":
            return bool(WAYLAND_SHELL_KEEP.search(name))
        return True
    if "/translations/" in posix or posix.startswith("translations/"):
        return name.endswith(".qm") is False or bool(TRANSLATIONS_KEEP.match(name))
    for part in parts:
        if part.endswith(".framework") and part.startswith("Qt"):
            return part[2 : -len(".framework")] in QT_LIBS_KEEP
    lib = _QT_LIB.match(name)
    if lib:
        return lib.group(1) in QT_LIBS_KEEP
    module = _PYSIDE_MODULE.match(name)
    if module and "PySide6" in parts:
        return module.group(1) in PYSIDE_MODULES_KEEP
    return True
