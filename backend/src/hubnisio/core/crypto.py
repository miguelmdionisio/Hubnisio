"""Encryption for provider secrets (ADR-0004): AES-GCM with versioned keys.

The keys file holds one key per line, as `v<n>:<base64 of 32 bytes>`; blank lines and `#`
comments are ignored. The highest version encrypts and every listed version decrypts, so a
key is rotated by appending a new one (scripts/generate_encryption_key.py) and re-encrypting.

Callers pass associated data naming the row a secret belongs to, e.g.
`finance.connections:<id>`. A ciphertext copied onto another row then fails to decrypt.
"""

import base64
import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Self

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from hubnisio.core.settings import get_settings

KEY_BYTES = 32
NONCE_BYTES = 12
_KEY_LINE = re.compile(r"v(\d+):(\S+)")


class SecretBox:
    def __init__(self, keys: dict[int, bytes]) -> None:
        if not keys:
            raise ValueError("No encryption keys given.")
        for version, key in keys.items():
            if len(key) != KEY_BYTES:
                raise ValueError(f"Encryption key v{version} is not {KEY_BYTES} bytes.")
        self._ciphers = {version: AESGCM(key) for version, key in keys.items()}
        self.current_version = max(keys)

    @classmethod
    def from_file(cls, path: Path) -> Self:
        keys: dict[int, bytes] = {}
        for number, raw_line in enumerate(path.read_text().splitlines(), start=1):
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            match = _KEY_LINE.fullmatch(line)
            if match is None:
                raise ValueError(f"{path}, line {number}: expected v<n>:<base64 key>.")
            version = int(match[1])
            if version in keys:
                raise ValueError(f"{path}, line {number}: key v{version} is listed twice.")
            keys[version] = base64.b64decode(match[2], validate=True)
        return cls(keys)

    def encrypt(self, plaintext: str, associated_data: str) -> str:
        nonce = os.urandom(NONCE_BYTES)
        sealed = self._ciphers[self.current_version].encrypt(
            nonce, plaintext.encode(), associated_data.encode()
        )
        return f"v{self.current_version}:{base64.b64encode(nonce + sealed).decode()}"

    def decrypt(self, token: str, associated_data: str) -> str:
        """Raises cryptography's InvalidTag if the token was altered or belongs to another row."""
        match = _KEY_LINE.fullmatch(token)
        if match is None:
            raise ValueError("Not an encrypted value.")
        version = int(match[1])
        cipher = self._ciphers.get(version)
        if cipher is None:
            raise ValueError(f"Encryption key v{version} is not in the keys file.")
        raw = base64.b64decode(match[2], validate=True)
        return cipher.decrypt(
            raw[:NONCE_BYTES], raw[NONCE_BYTES:], associated_data.encode()
        ).decode()


@lru_cache
def get_secret_box() -> SecretBox:
    return SecretBox.from_file(get_settings().encryption_keys_file)
