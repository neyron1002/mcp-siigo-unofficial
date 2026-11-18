# PyInstaller spec: the app as a one-folder build (Windows, Linux) or a .app (macOS).
# Plan D20: ship only what the app needs. Every exclusion below is proven safe by
# `--selftest` on the built app (CI runs it on all three systems).
# ruff: noqa
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata

ROOT = Path(SPECPATH).parent  # noqa: F821 - provided by PyInstaller
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "packaging"))
from mcp_siigo_unofficial import __version__  # noqa: E402
from qt_filter import keep  # noqa: E402

WINDOWS = sys.platform.startswith("win")
MACOS = sys.platform == "darwin"
APP_NAME = "MCP Siigo Unofficial"
EXE_NAME = "MCPSiigoUnofficial" if (WINDOWS or MACOS) else "mcp-siigo-unofficial"

# ---------------------------------------------------------------- Python modules
EXCLUDES = [
    # Standard library parts the app never uses (plan 3.2, item 3).
    "tkinter", "_tkinter", "turtle", "turtledemo", "idlelib", "lib2to3", "ensurepip",
    "pydoc", "pydoc_data", "unittest", "test", "doctest", "venv",
    "xmlrpc", "curses", "dbm", "sqlite3.test", "lib2to3",
    # Development tools that must never reach the bundle.
    "setuptools", "pkg_resources", "pip", "pytest", "_pytest", "mypy", "ruff",
    "IPython", "PyInstaller", "yaml",
    # Qt for Python modules the app does not import (plan 3.2, item 1).
    "PySide6.QtNetwork", "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuickWidgets",
    "PySide6.QtQuickControls2", "PySide6.QtSvg", "PySide6.QtSvgWidgets",
    "PySide6.QtOpenGL", "PySide6.QtOpenGLWidgets", "PySide6.QtPrintSupport",
    "PySide6.QtSql", "PySide6.QtTest", "PySide6.QtXml", "PySide6.QtConcurrent",
    "PySide6.QtDesigner", "PySide6.QtHelp", "PySide6.QtUiTools", "PySide6.QtPdf",
    "PySide6.QtPdfWidgets", "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets",
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtCharts",
    "PySide6.QtDataVisualization", "PySide6.QtBluetooth", "PySide6.QtNfc",
    "PySide6.QtPositioning", "PySide6.QtSensors", "PySide6.QtSerialPort",
    "PySide6.QtStateMachine", "PySide6.QtTextToSpeech", "PySide6.QtWebSockets",
    "PySide6.QtHttpServer", "PySide6.QtSpatialAudio", "PySide6.QtGraphs",
    "PySide6.QtExampleIcons", "PySide6.scripts",
]

HIDDEN = [
    # keyring discovers its OS backends through entry points.
    "keyring.backends.Windows", "keyring.backends.macOS", "keyring.backends.SecretService",
    "keyring.backends.libsecret", "keyring.backends.kwallet", "keyring.backends.chainer",
    "keyring.backends.fail", "keyring.backends.null",
    *collect_submodules("uvicorn"),
]

DATAS = [
    *collect_data_files("mcp_siigo_unofficial", includes=["**/*.json", "**/*.pem", "py.typed"]),
    *copy_metadata("keyring"),
    *copy_metadata("mcp"),
    *copy_metadata("mcp-siigo-unofficial"),
]

a = Analysis(  # noqa: F821
    [str(ROOT / "packaging" / "entry_app.py")],
    pathex=[str(ROOT / "src")],
    hookspath=[str(ROOT / "packaging" / "hooks")],
    datas=DATAS,
    hiddenimports=HIDDEN,
    excludes=EXCLUDES,
    noarchive=False,
    optimize=1,  # never 2: FastMCP reads tool descriptions from docstrings (CLAUDE.md rule 2)
)

# ---------------------------------------------------------------- Qt trimming
# The hooks in packaging/hooks already skip unused plugins (so their dependencies
# are never collected); this final pass removes anything that still slipped in.
a.binaries = [entry for entry in a.binaries if keep(entry[0])]
a.datas = [entry for entry in a.datas if keep(entry[0])]

pyz = PYZ(a.pure)  # noqa: F821

exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=EXE_NAME,
    console=False,  # tray app; stdio still works when a client passes pipes
    strip=not WINDOWS,
    upx=False,  # plan 3.2, item 6
    argv_emulation=False,
    target_arch=None,
)

coll = COLLECT(  # noqa: F821
    exe,
    a.binaries,
    a.datas,
    strip=not WINDOWS,
    upx=False,
    name="app",
)

if MACOS:
    app = BUNDLE(  # noqa: F821
        coll,
        name=f"{APP_NAME}.app",
        bundle_identifier="com.neyron1002.mcp-siigo-unofficial",
        version=__version__,
        info_plist={
            "CFBundleName": APP_NAME,
            "CFBundleDisplayName": APP_NAME,
            "CFBundleShortVersionString": __version__.split("-")[0],
            "LSUIElement": True,  # tray app: no Dock icon
            "LSMinimumSystemVersion": "13.0",
            "NSHighResolutionCapable": True,
        },
    )
