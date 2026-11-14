"""Reading and writing the encrypted state file."""

from __future__ import annotations

import json
import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from wichteln.errors import StateError
from wichteln.model import State, from_dict, to_dict

STATE_FILE = "state.enc"
TMP_FILE = "state.enc.tmp"


def exists(dir: Path) -> bool:
    return (Path(dir) / STATE_FILE).exists()


def load(dir: Path, key: bytes) -> State:
    path = Path(dir) / STATE_FILE
    if not path.exists():
        raise StateError(
            "state.enc missing; restore it from the backup or run: wichteln draw --no-history"
        )
    try:
        fernet = Fernet(key)
    except ValueError:
        raise StateError("invalid key format") from None
    try:
        plain = fernet.decrypt(path.read_bytes())
    except InvalidToken:
        raise StateError("cannot decrypt: wrong key or damaged file") from None
    try:
        return from_dict(json.loads(plain.decode("utf-8")))
    except StateError:
        raise
    except (json.JSONDecodeError, UnicodeDecodeError, KeyError, TypeError, ValueError):
        raise StateError("malformed state") from None


def save(dir: Path, key: bytes, state: State) -> None:
    dir = Path(dir)
    payload = json.dumps(to_dict(state), separators=(",", ":"), ensure_ascii=False)
    token = Fernet(key).encrypt(payload.encode("utf-8"))
    tmp = dir / TMP_FILE
    tmp.unlink(missing_ok=True)
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(token)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, dir / STATE_FILE)
