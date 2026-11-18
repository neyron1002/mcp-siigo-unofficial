# PyInstaller spec: the single-file launcher (Windows and Linux).
#
#   MCP_SIIGO_PAYLOAD_DIR unset -> "launcher-core": the small installed launcher.
#   MCP_SIIGO_PAYLOAD_DIR=<dir> -> the downloadable file: launcher + payload.tar.xz +
#                                  payload.json + launcher-core (all as data).
#   MCP_SIIGO_OUTPUT_NAME       -> the executable name (without .exe).
# ruff: noqa
import os
import sys
from pathlib import Path

ROOT = Path(SPECPATH).parent  # noqa: F821 - provided by PyInstaller
WINDOWS = sys.platform.startswith("win")
payload_dir = os.environ.get("MCP_SIIGO_PAYLOAD_DIR")
name = os.environ.get("MCP_SIIGO_OUTPUT_NAME") or "launcher-core"

datas = []
if payload_dir:
    payload = Path(payload_dir)
    for item in ("payload.tar.xz", "payload.json", "launcher-core.exe" if WINDOWS else "launcher-core"):
        path = payload / item
        if not path.is_file():
            raise SystemExit(f"Missing {path}")
        datas.append((str(path), "."))

# The launcher uses only the standard library and platformdirs.
EXCLUDES = [
    "PySide6", "shiboken6", "mcp", "mcp_types", "pydantic", "pydantic_core", "starlette",
    "uvicorn", "httpx2", "httpcore2", "anyio", "cryptography", "keyring", "jsonschema",
    "opentelemetry", "jwt", "cffi", "click", "sse_starlette", "multipart",
    "mcp_siigo_unofficial.app", "mcp_siigo_unofficial.server", "mcp_siigo_unofficial.siigo",
    "mcp_siigo_unofficial.vault", "mcp_siigo_unofficial.selftest",
    "tkinter", "_tkinter", "unittest", "test", "pydoc", "pydoc_data", "lib2to3", "idlelib",
    "ensurepip", "setuptools", "pkg_resources", "pip", "xmlrpc", "email",
    "http", "urllib.request", "sqlite3", "_sqlite3", "asyncio", "multiprocessing",
    "curses", "ssl", "_ssl", "decimal", "_decimal", "ctypes.test",
]

a = Analysis(  # noqa: F821
    [str(ROOT / "packaging" / "entry_launcher.py")],
    pathex=[str(ROOT / "src")],
    datas=datas,
    excludes=EXCLUDES,
    optimize=1,
)
pyz = PYZ(a.pure)  # noqa: F821
exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name=name,
    console=False,  # no console window on double-click (Windows)
    strip=not WINDOWS,
    upx=False,  # plan 3.2, item 6
    runtime_tmpdir=None,
)
