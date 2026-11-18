"""Release signing tool (plan D11).

    python packaging/sign.py generate --private-out <path outside the repo>
    python packaging/sign.py sign <dir>      # needs RELEASE_SIGNING_KEY (PEM) in the env
    python packaging/sign.py verify <dir>    # uses the public key shipped with the app

``generate`` writes the private key with owner-only permissions and never prints it;
it writes the public key into the app package.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from cryptography.hazmat.primitives import serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: E402

from mcp_siigo_unofficial.update import signature  # noqa: E402

PUBLIC_KEY_PATH = ROOT / "src" / "mcp_siigo_unofficial" / "update" / "release_public_key.pem"


def generate(private_out: Path) -> int:
    if private_out.resolve().is_relative_to(ROOT):
        raise SystemExit("Refusing to write the private key inside the repository.")
    if private_out.exists():
        raise SystemExit(f"{private_out} already exists; not overwriting it.")
    key = Ed25519PrivateKey.generate()
    private_out.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(private_out, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(
            key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
        )
    PUBLIC_KEY_PATH.write_bytes(
        key.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        )
    )
    print(f"Private key written to {private_out} (not printed). Public key: {PUBLIC_KEY_PATH}")
    return 0


def sign_dir(directory: Path) -> int:
    pem = os.environ.get("RELEASE_SIGNING_KEY", "").encode()
    if not pem.strip():
        raise SystemExit("RELEASE_SIGNING_KEY is not set.")
    key = signature.load_private_key(pem)
    files = [
        p
        for p in directory.iterdir()
        if p.is_file() and p.name not in {signature.SUMS_NAME, signature.SIGNATURE_NAME}
    ]
    sums = signature.make_sha256sums(files)
    sig = signature.sign(sums, key)
    signature.verify(sums, sig)  # the secret must match the public key the app ships
    (directory / signature.SUMS_NAME).write_bytes(sums)
    (directory / signature.SIGNATURE_NAME).write_bytes(sig)
    print(sums.decode())
    return 0


def verify_dir(directory: Path, *, present_only: bool = False) -> int:
    sums = (directory / signature.SUMS_NAME).read_bytes()
    sig = (directory / signature.SIGNATURE_NAME).read_bytes()
    signature.verify(sums, sig)
    checked = 0
    for name in signature.parse_sha256sums(sums):
        if present_only and not (directory / name).exists():
            continue
        signature.verify_file(directory / name, sums, sig)
        checked += 1
        print(f"ok  {name}")
    if checked == 0:
        raise SystemExit("No file listed in SHA256SUMS was found.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    gen = sub.add_parser("generate")
    gen.add_argument("--private-out", type=Path, required=True)
    sub.add_parser("sign").add_argument("directory", type=Path)
    ver = sub.add_parser("verify")
    ver.add_argument("directory", type=Path)
    ver.add_argument("--present-only", action="store_true", help="skip files not downloaded")
    args = parser.parse_args()
    if args.command == "generate":
        return generate(args.private_out)
    if args.command == "sign":
        return sign_dir(args.directory)
    return verify_dir(args.directory, present_only=args.present_only)


if __name__ == "__main__":
    raise SystemExit(main())
