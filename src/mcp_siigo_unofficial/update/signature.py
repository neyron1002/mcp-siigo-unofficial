"""Release integrity (plan D11): ``SHA256SUMS`` signed with Ed25519.

Each GitHub Release has ``SHA256SUMS`` (``<sha256>  <file name>`` per line) and
``SHA256SUMS.sig`` (the base64 Ed25519 signature of ``SHA256SUMS``). The private key
lives only in the GitHub secret ``RELEASE_SIGNING_KEY``; the public key is shipped
inside the app (``release_public_key.pem``) and committed in the repository.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import re
from functools import cache
from importlib import resources
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

SUMS_NAME = "SHA256SUMS"
SIGNATURE_NAME = "SHA256SUMS.sig"
_LINE = re.compile(r"^([0-9a-f]{64})  ([^/\\\s][^/\\]*)$")


class SignatureError(Exception):
    """The checksums or their signature are invalid."""


@cache
def release_public_key() -> Ed25519PublicKey:
    """The public key shipped with the app."""
    pem = resources.files(__package__).joinpath("release_public_key.pem").read_bytes()
    return load_public_key(pem)


def load_public_key(pem: bytes) -> Ed25519PublicKey:
    key = serialization.load_pem_public_key(pem)
    if not isinstance(key, Ed25519PublicKey):
        raise SignatureError("The release public key is not an Ed25519 key.")
    return key


def load_private_key(pem: bytes) -> Ed25519PrivateKey:
    key = serialization.load_pem_private_key(pem, password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise SignatureError("The release signing key is not an Ed25519 key.")
    return key


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def make_sha256sums(files: list[Path]) -> bytes:
    lines = [f"{sha256_file(p)}  {p.name}" for p in sorted(files, key=lambda p: p.name)]
    return ("\n".join(lines) + "\n").encode("utf-8")


def parse_sha256sums(data: bytes) -> dict[str, str]:
    """File name -> SHA-256. Rejects malformed lines and path separators."""
    result: dict[str, str] = {}
    for raw in data.decode("utf-8").splitlines():
        if not raw.strip():
            continue
        match = _LINE.match(raw)
        if not match or match.group(2) in result:
            raise SignatureError(f"Malformed {SUMS_NAME} line: {raw[:80]!r}")
        result[match.group(2)] = match.group(1)
    if not result:
        raise SignatureError(f"{SUMS_NAME} is empty.")
    return result


def sign(sums: bytes, private_key: Ed25519PrivateKey) -> bytes:
    """The base64 signature file content."""
    return base64.b64encode(private_key.sign(sums)) + b"\n"


def verify(sums: bytes, signature: bytes, public_key: Ed25519PublicKey | None = None) -> None:
    """Raise :class:`SignatureError` unless ``signature`` signs ``sums``."""
    key = public_key or release_public_key()
    try:
        raw = base64.b64decode(signature.strip(), validate=True)
        key.verify(raw, sums)
    except (InvalidSignature, binascii.Error, ValueError) as exc:
        raise SignatureError(f"{SIGNATURE_NAME} does not match {SUMS_NAME}.") from exc


def verify_file(
    path: Path,
    sums: bytes,
    signature: bytes,
    public_key: Ed25519PublicKey | None = None,
    *,
    name: str | None = None,
) -> None:
    """Verify the signature, then that ``path`` matches its signed checksum.

    ``name`` is the file's name in ``SHA256SUMS`` when it differs from ``path.name``
    (a download still in its ``.partial`` file).
    """
    verify(sums, signature, public_key)
    listed = name or path.name
    expected = parse_sha256sums(sums).get(listed)
    if expected is None:
        raise SignatureError(f"{listed} is not listed in {SUMS_NAME}.")
    if sha256_file(path) != expected:
        raise SignatureError(f"{listed} does not match its signed SHA-256.")
