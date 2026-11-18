"""Build the single downloadable file for this operating system (plan section 3).

Steps: (1) PyInstaller one-folder build of the app; (2) LZMA payload + manifest
(Windows, Linux) or a DMG (macOS); (3) the launcher with the payload inside;
(4) a size report and the size-budget check (plan 3.2, item 7).

Usage (in CI, or in the dev container for Linux)::

    uv run --group build python packaging/build.py [--out dist-release]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import lzma
import os
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mcp_siigo_unofficial import __version__  # noqa: E402
from mcp_siigo_unofficial.update.assets import artifact_name, target  # noqa: E402

WINDOWS = sys.platform.startswith("win")
MACOS = sys.platform == "darwin"
APP_NAME = "MCP Siigo Unofficial"
BUDGET_FILE = ROOT / "packaging" / "size_budget.json"
BUDGET_TOLERANCE = 0.10


def run(command: list[str], **env: str) -> None:
    print("+", " ".join(command), flush=True)
    subprocess.run(command, check=True, cwd=ROOT, env={**os.environ, **env})  # noqa: S603


def pyinstaller(spec: str, work: Path, dist: Path, **env: str) -> None:
    run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            str(ROOT / "packaging" / spec),
            "--noconfirm",
            "--clean",
            "--distpath",
            str(dist),
            "--workpath",
            str(work),
        ],
        **env,
    )


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def make_payload(app_dir: Path, out_dir: Path) -> Path:
    """tar.xz of the one-folder app (LZMA, plan 3.2 item 5) and its manifest."""
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = out_dir / "payload.tar.xz"
    files = sorted(p for p in app_dir.rglob("*") if p.is_file() or p.is_symlink())
    with (
        lzma.open(payload, "wb", preset=9 | lzma.PRESET_EXTREME) as xz,
        tarfile.open(fileobj=xz, mode="w", format=tarfile.PAX_FORMAT) as archive,
    ):
        for path in files:
            archive.add(path, arcname=path.relative_to(app_dir).as_posix(), recursive=False)
    exe = "MCPSiigoUnofficial.exe" if WINDOWS else "mcp-siigo-unofficial"
    manifest = {"version": __version__, "sha256": sha256(payload), "app_exe": exe}
    (out_dir / "payload.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return payload


def make_dmg(app_bundle: Path, out: Path) -> None:
    """DMG with the .app and an Applications shortcut (plan P5 = B)."""
    staging = out.parent / "dmg-staging"
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    run(["ditto", str(app_bundle), str(staging / app_bundle.name)])
    (staging / "Applications").symlink_to("/Applications")
    out.unlink(missing_ok=True)
    # ULMO = LZMA-compressed image (macOS 10.15+), smaller than the default zlib (UDZO).
    run(
        [
            "hdiutil",
            "create",
            "-volname",
            APP_NAME,
            "-srcfolder",
            str(staging),
            "-ov",
            "-format",
            "ULMO",
            str(out),
        ]
    )
    shutil.rmtree(staging, ignore_errors=True)


def size_report(artifact: Path, unpacked: Path) -> dict[str, object]:
    files = [p for p in unpacked.rglob("*") if p.is_file() and not p.is_symlink()]
    largest = sorted(files, key=lambda p: p.stat().st_size, reverse=True)[:20]
    return {
        "target": target(),
        "version": __version__,
        "artifact": artifact.name,
        "artifact_bytes": artifact.stat().st_size,
        "unpacked_bytes": sum(p.stat().st_size for p in files),
        "unpacked_files": len(files),
        "largest": [
            {"path": p.relative_to(unpacked).as_posix(), "bytes": p.stat().st_size} for p in largest
        ],
    }


def report_markdown(report: dict[str, object], budget: int | None) -> str:
    mb = 1024 * 1024
    lines = [
        f"## Size report: {report['artifact']}",
        "",
        f"- Download: **{int(report['artifact_bytes']) / mb:.1f} MB**"  # type: ignore[call-overload]
        + (f" (budget {budget / mb:.1f} MB + 10%)" if budget else " (no budget yet)"),
        f"- Unpacked: {int(report['unpacked_bytes']) / mb:.1f} MB in "  # type: ignore[call-overload]
        f"{report['unpacked_files']} files",
        "",
        "| # | File | MB |",
        "|---|---|---|",
    ]
    for i, item in enumerate(report["largest"], 1):  # type: ignore[arg-type]
        lines.append(f"| {i} | `{item['path']}` | {item['bytes'] / mb:.2f} |")
    return "\n".join(lines) + "\n"


def check_budget(report: dict[str, object]) -> tuple[int | None, bool]:
    budgets = json.loads(BUDGET_FILE.read_text(encoding="utf-8")) if BUDGET_FILE.exists() else {}
    budget = budgets.get("targets", {}).get(target())
    if budget is None:
        return None, True
    limit = int(budget * (1 + BUDGET_TOLERANCE))
    return int(budget), int(report["artifact_bytes"]) <= limit  # type: ignore[call-overload]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=ROOT / "dist-release")
    args = parser.parse_args()
    out: Path = args.out.resolve()
    work = ROOT / "build" / "pyinstaller"
    shutil.rmtree(work, ignore_errors=True)
    out.mkdir(parents=True, exist_ok=True)

    app_dist = work / "app-dist"
    pyinstaller("app.spec", work / "app-work", app_dist)
    artifact = out / artifact_name()
    if MACOS:
        bundle = app_dist / f"{APP_NAME}.app"
        make_dmg(bundle, artifact)
        unpacked = bundle
    else:
        unpacked = app_dist / "app"
        payload_dir = work / "payload"
        make_payload(unpacked, payload_dir)
        core_dist = work / "core-dist"
        pyinstaller("launcher.spec", work / "core-work", core_dist)
        core = core_dist / ("launcher-core.exe" if WINDOWS else "launcher-core")
        shutil.copy2(core, payload_dir / core.name)
        bundle_dist = work / "bundle-dist"
        stem = artifact.name.removesuffix(".exe")
        pyinstaller(
            "launcher.spec",
            work / "bundle-work",
            bundle_dist,
            MCP_SIIGO_PAYLOAD_DIR=str(payload_dir),
            MCP_SIIGO_OUTPUT_NAME=stem,
        )
        shutil.copy2(bundle_dist / artifact.name, artifact)

    report = size_report(artifact, unpacked)
    budget, within = check_budget(report)
    (out / f"size-report-{target()}.json").write_text(json.dumps(report, indent=2) + "\n")
    markdown = report_markdown(report, budget)
    (out / f"size-report-{target()}.md").write_text(markdown, encoding="utf-8")
    print(markdown)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as handle:
            handle.write(markdown)
    if not within:
        print(f"ERROR: {artifact.name} is more than 10% over the size budget.", file=sys.stderr)
        return 2
    print(f"Built {artifact}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
