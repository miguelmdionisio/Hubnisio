"""Append a new key version to the encryption keys file (see hubnisio.core.crypto).

From backend/: uv run python scripts/generate_encryption_key.py ../secrets/encryption-keys

The new key encrypts from then on; older versions stay in the file so existing values still
decrypt. Keep a copy of the file in your password manager (ADR-0004).
"""

import argparse
import base64
import re
import secrets
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Append a new encryption key version.")
    parser.add_argument("path", type=Path, help="keys file; created if it doesn't exist")
    path: Path = parser.parse_args().path

    existing = path.read_text() if path.exists() else ""
    versions = [int(match[1]) for match in re.finditer(r"^v(\d+):", existing, re.MULTILINE)]
    version = max(versions, default=0) + 1
    key = base64.b64encode(secrets.token_bytes(32)).decode()

    path.parent.mkdir(parents=True, exist_ok=True)
    separator = "\n" if existing and not existing.endswith("\n") else ""
    with path.open("a", newline="\n") as file:
        file.write(f"{separator}v{version}:{key}\n")
    print(f"Added key v{version} to {path}.")


if __name__ == "__main__":
    main()
