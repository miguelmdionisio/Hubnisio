import base64
import os
import runpy
import sys
from pathlib import Path

import pytest
from cryptography.exceptions import InvalidTag

from hubnisio.core.crypto import SecretBox

KEY_1 = os.urandom(32)
KEY_2 = os.urandom(32)
KEY_1_LINE = f"v1:{base64.b64encode(KEY_1).decode()}"
KEY_2_LINE = f"v2:{base64.b64encode(KEY_2).decode()}"
GENERATE_SCRIPT = Path(__file__).parents[1] / "scripts" / "generate_encryption_key.py"


def test_round_trip() -> None:
    box = SecretBox({1: KEY_1})
    token = box.encrypt("session-123", "finance.connections:abc")

    assert token.startswith("v1:")
    assert "session-123" not in token
    assert box.decrypt(token, "finance.connections:abc") == "session-123"


def test_ciphertext_is_bound_to_its_row() -> None:
    box = SecretBox({1: KEY_1})
    token = box.encrypt("session-123", "finance.connections:abc")

    with pytest.raises(InvalidTag):
        box.decrypt(token, "finance.connections:other")


def test_tampered_ciphertext_is_rejected() -> None:
    box = SecretBox({1: KEY_1})
    version, body = box.encrypt("session-123", "row").split(":")
    raw = bytearray(base64.b64decode(body))
    raw[-1] ^= 1
    tampered = f"{version}:{base64.b64encode(raw).decode()}"

    with pytest.raises(InvalidTag):
        box.decrypt(tampered, "row")


def test_rotation_keeps_old_values_readable() -> None:
    old_token = SecretBox({1: KEY_1}).encrypt("session-123", "row")
    rotated = SecretBox({1: KEY_1, 2: KEY_2})

    assert rotated.decrypt(old_token, "row") == "session-123"
    assert rotated.encrypt("session-123", "row").startswith("v2:")


def test_unknown_key_version_is_reported() -> None:
    token = SecretBox({2: KEY_2}).encrypt("session-123", "row")

    with pytest.raises(ValueError, match="v2 is not in the keys file"):
        SecretBox({1: KEY_1}).decrypt(token, "row")


def test_keys_must_be_32_bytes() -> None:
    with pytest.raises(ValueError, match="not 32 bytes"):
        SecretBox({1: b"short"})


def test_from_file_skips_comments_and_blank_lines(tmp_path: Path) -> None:
    path = tmp_path / "keys"
    path.write_text(f"# rotated 2026-10\n\n{KEY_1_LINE}\n{KEY_2_LINE}\n")

    assert SecretBox.from_file(path).current_version == 2


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("not-a-key\n", "line 1: expected"),
        ("v1:AAAA\n", "not 32 bytes"),
        (f"{KEY_1_LINE}\n{KEY_1_LINE}\n", "line 2: key v1 is listed twice"),
    ],
)
def test_from_file_rejects_bad_files(tmp_path: Path, content: str, message: str) -> None:
    path = tmp_path / "keys"
    path.write_text(content)

    with pytest.raises(ValueError, match=message):
        SecretBox.from_file(path)


def test_generate_script_appends_versions(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "secrets" / "encryption-keys"
    monkeypatch.setattr(sys, "argv", ["generate_encryption_key.py", str(path)])

    runpy.run_path(str(GENERATE_SCRIPT), run_name="__main__")
    first = SecretBox.from_file(path)
    runpy.run_path(str(GENERATE_SCRIPT), run_name="__main__")
    second = SecretBox.from_file(path)

    assert first.current_version == 1
    assert second.current_version == 2
    assert second.decrypt(first.encrypt("session-123", "row"), "row") == "session-123"
