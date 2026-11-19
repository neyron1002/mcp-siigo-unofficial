"""Release signatures (plan D11) and the Qt file filter used by the build (D20)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from mcp_siigo_unofficial.update import signature
from mcp_siigo_unofficial.update.signature import SignatureError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packaging"))
from qt_filter import keep


@pytest.fixture
def key() -> Ed25519PrivateKey:
    return Ed25519PrivateKey.generate()


@pytest.fixture
def release(tmp_path: Path) -> list[Path]:
    files = []
    for name, content in (("app-linux-x64", b"linux"), ("app-windows-x64.exe", b"win")):
        path = tmp_path / name
        path.write_bytes(content)
        files.append(path)
    return files


def test_sign_and_verify(key: Ed25519PrivateKey, release: list[Path]) -> None:
    sums = signature.make_sha256sums(release)
    sig = signature.sign(sums, key)
    signature.verify(sums, sig, key.public_key())
    for path in release:
        signature.verify_file(path, sums, sig, key.public_key())
    assert set(signature.parse_sha256sums(sums)) == {"app-linux-x64", "app-windows-x64.exe"}


def test_tampering_is_detected(key: Ed25519PrivateKey, release: list[Path]) -> None:
    sums = signature.make_sha256sums(release)
    sig = signature.sign(sums, key)
    with pytest.raises(SignatureError):
        signature.verify(sums.replace(b"linux", b"Linux"), sig, key.public_key())
    with pytest.raises(SignatureError):
        signature.verify(sums, sig, Ed25519PrivateKey.generate().public_key())
    with pytest.raises(SignatureError):
        signature.verify(sums, b"not base64!", key.public_key())
    release[0].write_bytes(b"changed")
    with pytest.raises(SignatureError, match="does not match its signed"):
        signature.verify_file(release[0], sums, sig, key.public_key())
    other = release[0].with_name("unlisted")
    other.write_bytes(b"x")
    with pytest.raises(SignatureError, match="not listed"):
        signature.verify_file(other, sums, sig, key.public_key())


@pytest.mark.parametrize(
    "content",
    [
        b"",
        b"zz  file\n",
        b"%s  ../evil\n" % (b"a" * 64),
        b"%s  a/b\n" % (b"a" * 64),
        b"%s  f\n%s  f\n" % (b"a" * 64, b"b" * 64),
    ],
)
def test_malformed_sums_are_rejected(content: bytes) -> None:
    with pytest.raises(SignatureError):
        signature.parse_sha256sums(content)


def test_key_type_checks(key: Ed25519PrivateKey) -> None:
    pem = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )
    assert signature.load_private_key(pem).public_key() == key.public_key()
    from cryptography.hazmat.primitives.asymmetric import ec

    other = (
        ec.generate_private_key(ec.SECP256R1())
        .public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    )
    with pytest.raises(SignatureError, match="Ed25519"):
        signature.load_public_key(other)


@pytest.mark.parametrize(
    ("path", "kept"),
    [
        ("PySide6/Qt/plugins/platforms/libqxcb.so", True),
        ("PySide6/Qt/plugins/platforms/libqoffscreen.so", True),
        ("PySide6/Qt/plugins/platforms/libqwayland-generic.so", True),
        ("PySide6/Qt/plugins/platforms/libqwayland-egl.so", False),
        ("PySide6/Qt/plugins/platforms/libqvnc.so", False),
        ("PySide6/plugins/platforms/qwindows.dll", True),
        ("PySide6/Qt/plugins/platforms/libqcocoa.dylib", True),
        ("PySide6/Qt/plugins/imageformats/libqjpeg.so", False),
        ("PySide6/Qt/plugins/platformthemes/libqgtk3.so", False),
        ("PySide6/Qt/plugins/platforminputcontexts/libibusplatforminputcontextplugin.so", True),
        ("PySide6/Qt/plugins/wayland-shell-integration/libxdg-shell.so", True),
        ("PySide6/Qt/plugins/wayland-shell-integration/libivi-shell.so", False),
        ("PySide6/Qt/translations/qtbase_es.qm", True),
        ("PySide6/Qt/translations/qtbase_de.qm", False),
        ("PySide6/Qt/lib/libQt6Network.so.6", False),
        ("libQt6Svg.so.6", False),
        ("PySide6/Qt/lib/libQt6Widgets.so.6", True),
        ("PySide6/Qt6Core.dll", True),
        ("PySide6/Qt6Quick.dll", False),
        ("PySide6/Qt/lib/QtGui.framework/Versions/A/QtGui", True),
        ("PySide6/Qt/lib/QtQml.framework/Versions/A/QtQml", False),
        ("PySide6/QtNetwork.abi3.so", False),
        ("PySide6/QtWidgets.pyd", True),
        ("PySide6/Qt/lib/libicudata.so.73", True),
        ("cryptography/hazmat/bindings/_rust.abi3.so", True),
    ],
)
def test_qt_filter(path: str, kept: bool) -> None:
    assert keep(path) is kept


def test_previous_release_for_the_update_test() -> None:
    import importlib.util
    from pathlib import Path

    path = Path(__file__).parents[1] / "packaging" / "previous_release.py"
    spec = importlib.util.spec_from_file_location("previous_release", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    releases = [
        {"tag_name": "v0.1.0-rc.2"},
        {"tag_name": "v0.1.0-rc.1"},
        {"tag_name": "v0.1.0-rc.3", "draft": True},
        {"tag_name": "nightly"},
    ]
    assert module.previous_tag(releases, "v0.1.0-rc.2") == "v0.1.0-rc.1"
    assert module.previous_tag(releases, "v0.1.0") is None  # no older stable release
    assert module.previous_tag(releases, "v0.1.0-rc.1") is None
    # A pre-release after a stable release starts from the newest older pre-release.
    later = [*releases, {"tag_name": "v0.1.0"}, {"tag_name": "v0.1.1-rc.1"}]
    assert module.previous_tag(later, "v0.1.1-rc.1") == "v0.1.0-rc.2"
    assert module.previous_tag(later, "v0.1.2-rc.1") == "v0.1.1-rc.1"
    # A stable tag starts from the newest older stable release (what users have).
    assert module.previous_tag(later, "v0.2.0") == "v0.1.0"
