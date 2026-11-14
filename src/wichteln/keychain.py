"""macOS Keychain access through /usr/bin/security. Secret values are never printed."""

from __future__ import annotations

import re
import subprocess

from wichteln.errors import StateError

SECURITY = "/usr/bin/security"
SERVICE = "wichteln"
FERNET_ACCOUNT = "fernet-key"
SMTP_ACCOUNT = "smtp"
_ITEM_NOT_FOUND = 44
_FERNET_KEY = re.compile(r"[A-Za-z0-9_-]{43}=")


class SecretMissing(StateError):
    """The Keychain has no item for the account."""


def get_secret(account: str) -> str:
    proc = subprocess.run(
        [SECURITY, "find-generic-password", "-s", SERVICE, "-a", account, "-w"],
        capture_output=True,
        text=True,
    )
    if proc.returncode == 0:
        return proc.stdout.removesuffix("\n")
    if proc.returncode == _ITEM_NOT_FOUND:
        raise SecretMissing(
            f"Keychain item {account} missing; restore it with: "
            f"security add-generic-password -s {SERVICE} -a {account} -U -w"
        )
    raise StateError(f"keychain access failed (exit {proc.returncode})")


def store_fernet_key(key: str) -> None:
    if not _FERNET_KEY.fullmatch(key):
        raise ValueError("not a Fernet key")
    subprocess.run(
        [SECURITY, "-i"],
        input=f"add-generic-password -s {SERVICE} -a {FERNET_ACCOUNT} -U -w {key}\n",
        capture_output=True,
        text=True,
    )
    try:
        stored = get_secret(FERNET_ACCOUNT)
    except StateError:
        stored = None
    if stored != key:
        raise StateError("storing the key in the Keychain failed")
