"""AES-256-GCM field encryption."""

from __future__ import annotations

import pytest

from mcp_siigo_unofficial.vault import crypto


def test_round_trip() -> None:
    key = crypto.generate_key()
    blob = crypto.encrypt(key, "siigo.access_key", "sécret ✓".encode())
    assert crypto.decrypt(key, "siigo.access_key", blob).decode() == "sécret ✓"


def test_ciphertext_hides_plaintext_and_uses_fresh_nonces() -> None:
    key = crypto.generate_key()
    first = crypto.encrypt(key, "f", b"same value")
    second = crypto.encrypt(key, "f", b"same value")
    assert first != second
    assert b"same value" not in first
    assert len(first) == 1 + crypto.NONCE_SIZE + len(b"same value") + 16


@pytest.mark.parametrize(
    ("key_kind", "field"),
    [("other", "f"), ("same", "other-field")],
)
def test_wrong_key_or_field_fails(key_kind: str, field: str) -> None:
    key = crypto.generate_key()
    blob = crypto.encrypt(key, "f", b"value")
    used = crypto.generate_key() if key_kind == "other" else key
    with pytest.raises(crypto.VaultCryptoError):
        crypto.decrypt(used, field, blob)


def test_tampered_blob_fails() -> None:
    key = crypto.generate_key()
    blob = bytearray(crypto.encrypt(key, "f", b"value"))
    blob[-1] ^= 0x01
    with pytest.raises(crypto.VaultCryptoError):
        crypto.decrypt(key, "f", bytes(blob))


@pytest.mark.parametrize("blob", [b"", b"\x02" + b"\x00" * 40, b"\x01short"])
def test_bad_format_fails(blob: bytes) -> None:
    with pytest.raises(crypto.VaultCryptoError):
        crypto.decrypt(crypto.generate_key(), "f", blob)


def test_key_size_is_checked() -> None:
    with pytest.raises(ValueError, match="32 bytes"):
        crypto.encrypt(b"short", "f", b"value")
