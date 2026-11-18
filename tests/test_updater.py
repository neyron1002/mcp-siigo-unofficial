"""Phase 5: update check, signed download, launcher update with rollback (plan section 3)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import httpx2
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from mcp_siigo_unofficial import __main__ as cli
from mcp_siigo_unofficial.launcher import core
from mcp_siigo_unofficial.launcher.core import (
    UPDATE_RESULT_NAME,
    Layout,
    install_payload,
    wait_for_pid,
)
from mcp_siigo_unofficial.update import apply, releases, signature
from mcp_siigo_unofficial.update.assets import artifact_name, target
from mcp_siigo_unofficial.update.releases import (
    Release,
    UpdateError,
    check_for_update,
    download_update,
    newest_update,
    parse_releases,
)
from mcp_siigo_unofficial.update.versions import is_newer, is_prerelease, version_key
from test_launcher import make_payload

POSIX_ONLY = pytest.mark.skipif(sys.platform.startswith("win"), reason="shell script app")
FAILING_APP = "#!/bin/sh\nexit 1\n"


# ---------------------------------------------------------------- versions and names
def test_semver_ordering() -> None:
    ordered = ["0.0.1", "0.1.0-rc.1", "0.1.0-rc.2", "0.1.0-rc.10", "0.1.0", "0.1.1", "1.0.0"]
    shuffled = [ordered[i] for i in (4, 0, 6, 2, 5, 1, 3)]
    assert sorted(shuffled, key=version_key) == ordered
    assert is_newer("v0.1.0-rc.2", "0.1.0-rc.1")
    assert not is_newer("0.1.0-rc.1", "0.1.0")
    assert is_prerelease("0.1.0-rc.1")
    assert not is_prerelease("0.1.0")
    with pytest.raises(ValueError, match="SemVer"):
        version_key("latest")


def test_artifact_names() -> None:
    assert artifact_name("0.1.0", "win32", "AMD64") == "MCPSiigoUnofficial-0.1.0-windows-x64.exe"
    assert artifact_name("0.1.0", "darwin", "arm64") == "MCPSiigoUnofficial-0.1.0-macos-arm64.dmg"
    assert artifact_name("0.1.0", "linux", "x86_64") == "mcp-siigo-unofficial-0.1.0-linux-x64"
    assert target("linux", "aarch64") == "linux-arm64"


# ---------------------------------------------------------------- choosing a release
def gh_release(tag: str, *, prerelease: bool = False, draft: bool = False, assets: bool = True):  # type: ignore[no-untyped-def]
    version = tag.removeprefix("v")
    names = [artifact_name(version), "SHA256SUMS", "SHA256SUMS.sig"] if assets else []
    return {
        "tag_name": tag,
        "prerelease": prerelease,
        "draft": draft,
        "html_url": f"https://example.invalid/{tag}",
        "assets": [
            {"name": n, "browser_download_url": f"https://dl.invalid/{tag}/{n}"} for n in names
        ],
    }


def test_newest_update_rules() -> None:
    data = [
        gh_release("v0.2.0-rc.1", prerelease=True),
        gh_release("v0.1.1"),
        gh_release("v0.1.2", assets=False),  # no file for this system: skipped
        gh_release("v0.3.0", draft=True),  # drafts are never offered
        gh_release("not-a-version"),
    ]
    found = parse_releases(data)
    assert [r.version for r in found] == ["0.2.0-rc.1", "0.1.1", "0.1.2"]
    stable = newest_update(found, "0.1.0")
    assert stable is not None
    assert stable.version == "0.1.1"  # stable builds skip pre-releases
    pre = newest_update(found, "0.1.0-rc.1")
    assert pre is not None
    assert pre.version == "0.2.0-rc.1"  # pre-release builds get them
    assert newest_update(found, "0.2.0") is None


def test_check_for_update_uses_the_api_and_the_optional_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(200, json=[gh_release("v9.0.0")])

    monkeypatch.setenv(releases.TOKEN_ENV, "test-token")
    with httpx2.Client(transport=httpx2.MockTransport(handler)) as client:
        found = check_for_update("1.0.0", client)
    assert found is not None
    assert found.version == "9.0.0"
    assert str(seen[0].url) == releases.RELEASES_API
    assert seen[0].headers["Authorization"] == "Bearer test-token"


def test_check_for_update_errors_are_readable() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(403, json={"message": "rate limited"})

    with (
        httpx2.Client(transport=httpx2.MockTransport(handler)) as client,
        pytest.raises(UpdateError, match="Could not check"),
    ):
        check_for_update("1.0.0", client)


# ---------------------------------------------------------------- signed download
@pytest.fixture
def signing_key(monkeypatch: pytest.MonkeyPatch) -> Ed25519PrivateKey:
    key = Ed25519PrivateKey.generate()
    monkeypatch.setattr(signature, "release_public_key", key.public_key)
    return key


def serve_release(
    tmp_path: Path, key: Ed25519PrivateKey, *, tamper: bool = False
) -> tuple[Release, httpx2.Client]:
    release = parse_releases([gh_release("v9.0.0")])[0]
    body = b"new release file"
    staged = tmp_path / "served" / release.file_name
    staged.parent.mkdir()
    staged.write_bytes(body)
    sums = signature.make_sha256sums([staged])
    files = {
        release.file_name: body + (b"!" if tamper else b""),
        "SHA256SUMS": sums,
        "SHA256SUMS.sig": signature.sign(sums, key),
    }

    def handler(request: httpx2.Request) -> httpx2.Response:
        assert "Authorization" not in request.headers  # downloads never carry a token
        return httpx2.Response(200, content=files[request.url.path.rsplit("/", 1)[-1]])

    return release, httpx2.Client(transport=httpx2.MockTransport(handler))


def test_download_is_verified(tmp_path: Path, signing_key: Ed25519PrivateKey) -> None:
    release, client = serve_release(tmp_path, signing_key)
    with client:
        path = download_update(release, tmp_path / "downloads", client)
    assert path.read_bytes() == b"new release file"
    assert path.name == release.file_name


def test_tampered_download_is_rejected(tmp_path: Path, signing_key: Ed25519PrivateKey) -> None:
    release, client = serve_release(tmp_path, signing_key, tamper=True)
    with client, pytest.raises(UpdateError, match="signature check"):
        download_update(release, tmp_path / "downloads", client)
    assert list((tmp_path / "downloads").iterdir()) == []


def test_download_signed_by_another_key_is_rejected(
    tmp_path: Path, signing_key: Ed25519PrivateKey
) -> None:
    release, client = serve_release(tmp_path, Ed25519PrivateKey.generate())
    with client, pytest.raises(UpdateError, match="signature check"):
        download_update(release, tmp_path / "downloads", client)


# ---------------------------------------------------------------- launcher --update
def finished_pid() -> int:
    process = subprocess.Popen([sys.executable, "-c", "pass"])
    process.wait()
    return process.pid


def test_wait_for_pid() -> None:
    assert wait_for_pid(finished_pid(), timeout=5)
    import os

    assert not wait_for_pid(os.getpid(), timeout=0.3)


def read_result(layout: Layout) -> dict[str, object]:
    return json.loads((layout.root / UPDATE_RESULT_NAME).read_text())  # type: ignore[no-any-return]


@POSIX_ONLY
def test_update_switches_after_the_selftest(tmp_path: Path) -> None:
    layout = Layout(tmp_path / "home")
    install_payload(make_payload(tmp_path, "1.0.0"), layout)
    assert (
        core.update(layout, make_payload(tmp_path, "2.0.0"), wait_pid=finished_pid(), start=False)
        == 0
    )
    assert layout.current_version() == "2.0.0"
    assert layout.previous_version() == "1.0.0"
    assert layout.is_installed("1.0.0")  # the previous version is kept
    ran = (layout.version_dir("2.0.0") / "ran.txt").read_text()
    assert ran.startswith("--selftest --offline|")
    assert read_result(layout) == {
        **read_result(layout),
        "from": "1.0.0",
        "to": "2.0.0",
        "ok": True,
    }
    assert "self-test" in (layout.root / core.UPDATE_LOG_NAME).read_text()


@POSIX_ONLY
def test_update_rolls_back_when_the_selftest_fails(tmp_path: Path) -> None:
    layout = Layout(tmp_path / "home")
    install_payload(make_payload(tmp_path, "1.0.0"), layout)
    bad = make_payload(tmp_path, "2.0.0", app_script=FAILING_APP)
    assert core.update(layout, bad, wait_pid=None, start=False) == 1
    assert layout.current_version() == "1.0.0"
    assert not layout.version_dir("2.0.0").exists()
    result = read_result(layout)
    assert (result["ok"], result["from"], result["to"]) == (False, "1.0.0", "2.0.0")


@POSIX_ONLY
def test_update_rolls_back_and_restarts_the_old_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    layout = Layout(tmp_path / "home")
    install_payload(make_payload(tmp_path, "1.0.0"), layout)
    started: list[tuple[str | None, list[str]]] = []
    monkeypatch.setattr(
        core, "run_app", lambda lay, args, wait: started.append((lay.current_version(), args)) or 0
    )
    bad = make_payload(tmp_path, "2.0.0", app_script=FAILING_APP)
    assert core.update(layout, bad, wait_pid=None, start=True) == 1
    assert started == [("1.0.0", ["--run"])]


def test_update_stops_when_the_old_app_keeps_running(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    layout = Layout(tmp_path / "home")
    monkeypatch.setattr(core, "wait_for_pid", lambda pid, timeout=120.0: False)
    with pytest.raises(core.LauncherError, match="did not exit"):
        core.update(layout, make_payload(tmp_path, "2.0.0"), wait_pid=1234, start=False)


def test_main_update_needs_the_payload(
    layout_home: Layout, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(core, "Layout", lambda: layout_home)
    monkeypatch.setattr(core, "bundle_dir", lambda: None)
    assert core.main(["--update", "--wait-pid", "1"]) == 1
    assert "payload" in capsys.readouterr().err


@POSIX_ONLY
def test_main_update_parses_its_options(
    tmp_path: Path, layout_home: Layout, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[int | None, bool]] = []
    monkeypatch.setattr(core, "Layout", lambda: layout_home)
    source = make_payload(tmp_path, "2.0.0")
    monkeypatch.setattr(core, "bundle_dir", lambda: source)
    monkeypatch.setattr(
        core, "update", lambda lay, src, wait_pid, start: calls.append((wait_pid, start)) or 0
    )
    assert core.main(["--update", "--wait-pid", "42", "--no-start"]) == 0
    assert core.main(["--update"]) == 0
    assert calls == [(42, False), (None, True)]


@pytest.fixture
def layout_home(tmp_path: Path) -> Layout:
    return Layout(tmp_path / "home")


# ---------------------------------------------------------------- the app side
def test_update_result_is_shown_once(tmp_path: Path) -> None:
    core.write_update_result(tmp_path, old="1.0.0", new="2.0.0", ok=True, detail="ok")
    result = apply.take_update_result(tmp_path)
    assert result is not None
    assert result["to"] == "2.0.0"
    assert apply.take_update_result(tmp_path) is None


def test_start_update_runs_the_downloaded_launcher(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spawned: list[list[str]] = []
    monkeypatch.setattr(apply, "MACOS", False)
    monkeypatch.setattr(apply, "_spawn_detached", spawned.append)
    apply.start_update(tmp_path / "new.exe", pid=77, start_app=False)
    apply.start_update(tmp_path / "new.exe", pid=77, start_app=True)
    assert spawned == [
        [str(tmp_path / "new.exe"), "--update", "--wait-pid", "77", "--no-start"],
        [str(tmp_path / "new.exe"), "--update", "--wait-pid", "77"],
    ]


def test_development_checkout_cannot_self_update() -> None:
    assert not apply.can_self_update()
    assert (
        apply.current_bundle("/Applications/X.app/Contents/MacOS/X")
        == Path("/Applications/X.app").resolve()
    )
    assert apply.current_bundle("/opt/x/bin/x") is None


def fake_bundle(folder: Path, name: str, script: str) -> Path:
    exe = folder / name / "Contents" / "MacOS" / Path(sys.executable).name
    exe.parent.mkdir(parents=True)
    exe.write_text(script)
    exe.chmod(0o755)
    return folder / name


@POSIX_ONLY
def test_macos_apply_swaps_the_app_and_keeps_the_previous_one(tmp_path: Path) -> None:
    target = fake_bundle(tmp_path / "Applications", "X.app", "#!/bin/sh\nexit 0\n")
    (target / "old-marker").write_text("old")
    staged = fake_bundle(tmp_path / "staging", "X.app", "#!/bin/sh\nexit 0\n")
    (staged / "new-marker").write_text("new")
    root = tmp_path / "data"
    assert (
        apply.apply_macos_update(staged, target, wait_pid=None, start=False, old="1", root=root)
        == 0
    )
    assert (target / "new-marker").exists()
    assert (root / "previous-app" / "X.app" / "old-marker").exists()
    assert apply.take_update_result(root)["ok"] is True  # type: ignore[index]


@POSIX_ONLY
def test_macos_apply_rolls_back_when_the_selftest_fails(tmp_path: Path) -> None:
    target = fake_bundle(tmp_path / "Applications", "X.app", "#!/bin/sh\nexit 0\n")
    staged = fake_bundle(tmp_path / "staging", "X.app", FAILING_APP)
    root = tmp_path / "data"
    assert (
        apply.apply_macos_update(staged, target, wait_pid=None, start=False, old="1", root=root)
        == 1
    )
    assert (target / "Contents").exists()
    assert not (root / "previous-app").exists()
    assert apply.take_update_result(root)["ok"] is False  # type: ignore[index]


def test_cli_update_now(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(releases, "check_for_update", lambda: None)
    assert cli.main(["--update-now"]) == 0
    assert "up to date" in capsys.readouterr().out
    newer = parse_releases([gh_release("v9.0.0")])[0]
    monkeypatch.setattr(releases, "check_for_update", lambda: newer)
    assert cli.main(["--update-now"]) == 1  # a development checkout cannot replace itself
    assert "9.0.0 is available" in capsys.readouterr().err
    monkeypatch.setattr(
        releases, "check_for_update", lambda: (_ for _ in ()).throw(UpdateError("offline"))
    )
    assert cli.main(["--update-now"]) == 1
    assert "offline" in capsys.readouterr().err


def test_cli_apply_update_outside_a_staged_app(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["--apply-update", "--target", "/tmp/X.app"]) == 2  # noqa: S108
    assert "staged macOS app" in capsys.readouterr().err
