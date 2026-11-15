"""Loading and checking participants.toml and config.toml.

No error message contains text from the files except participant IDs and key names.
"""

from __future__ import annotations

import os
import re
import tomllib
from email.utils import parseaddr
from pathlib import Path
from typing import Any

from wichteln.errors import ConfigError
from wichteln.model import ID_PATTERN, MailConfig, Participant, SmtpConfig

PARTICIPANTS_FILE = "participants.toml"
CONFIG_FILE = "config.toml"
MIN_PARTICIPANTS = 2
MAX_PARTICIPANTS = 10
_TOML_POS = re.compile(r"\(at line (\d+), column (\d+)\)")


def data_dir() -> Path:
    env = os.environ.get("WICHTELN_HOME")
    return Path(env) if env else Path.home() / "Wichteln"


def _read_toml(path: Path) -> dict[str, Any]:
    try:
        with open(path, "rb") as f:
            return tomllib.load(f)
    except FileNotFoundError:
        raise ConfigError(f"{path.name}: not found") from None
    except tomllib.TOMLDecodeError as exc:
        m = _TOML_POS.search(str(exc))
        if m:
            raise ConfigError(
                f"{path.name}: invalid TOML at line {m.group(1)}, column {m.group(2)}"
            ) from None
        raise ConfigError(f"{path.name}: invalid TOML") from None
    except UnicodeDecodeError:
        raise ConfigError(f"{path.name}: not valid UTF-8") from None
    except OSError as exc:
        raise ConfigError(f"{path.name}: cannot read ({type(exc).__name__})") from None


def valid_email(addr: str) -> bool:
    if addr.count("@") != 1 or any(c.isspace() for c in addr):
        return False
    local, _, domain = addr.partition("@")
    return bool(local) and "." in domain


def load_participants(path: Path) -> list[Participant]:
    name = path.name
    data = _read_toml(path)
    entries = data.get("participant")
    if not isinstance(entries, list) or not all(isinstance(e, dict) for e in entries):
        raise ConfigError(f"{name}: 'participant' must be a list of [[participant]] tables")

    result: list[Participant] = []
    seen_ids: set[str] = set()
    seen_emails: set[str] = set()
    for pos, entry in enumerate(entries, start=1):
        pid = entry.get("id")
        label = pid if isinstance(pid, str) and ID_PATTERN.fullmatch(pid) else f"entry {pos}"
        keys = set(entry)
        expected = {"id", "name", "email"}
        missing = sorted(expected - keys)
        if missing:
            raise ConfigError(f"{name}: {label}: missing key '{missing[0]}'")
        if keys - expected:
            # The key itself isn't printed: a mistyped key could be a name.
            raise ConfigError(f"{name}: {label}: unknown key")
        for key in ("id", "name", "email"):
            if not isinstance(entry[key], str):
                raise ConfigError(f"{name}: {label}: '{key}' must be a string")
        if not ID_PATTERN.fullmatch(pid):
            raise ConfigError(f"{name}: {label}: 'id' must be 1-32 characters of a-z, 0-9 or -")
        if pid in seen_ids:
            raise ConfigError(f"{name}: {pid}: duplicate 'id'")
        email = entry["email"]
        if not valid_email(email):
            raise ConfigError(f"{name}: {pid}: 'email' is not a valid address")
        if email.lower() in seen_emails:
            raise ConfigError(f"{name}: {pid}: duplicate 'email'")
        seen_ids.add(pid)
        seen_emails.add(email.lower())
        result.append(Participant(id=pid, name=entry["name"], email=email))

    if not MIN_PARTICIPANTS <= len(result) <= MAX_PARTICIPANTS:
        raise ConfigError(
            f"{name}: {len(result)} participants; "
            f"between {MIN_PARTICIPANTS} and {MAX_PARTICIPANTS} are needed"
        )
    return result


def _table(data: dict[str, Any], name: str, table: str) -> dict[str, Any]:
    value = data.get(table)
    if not isinstance(value, dict):
        raise ConfigError(f"{name}: missing table [{table}]")
    return value


def _string(table: dict[str, Any], name: str, prefix: str, key: str) -> str:
    if key not in table:
        raise ConfigError(f"{name}: missing key '{prefix}.{key}'")
    value = table[key]
    if not isinstance(value, str):
        raise ConfigError(f"{name}: '{prefix}.{key}' must be a string")
    return value


def load_config(path: Path) -> tuple[SmtpConfig, MailConfig]:
    name = path.name
    data = _read_toml(path)
    smtp = _table(data, name, "smtp")
    mail = _table(data, name, "mail")

    host = _string(smtp, name, "smtp", "host")
    username = _string(smtp, name, "smtp", "username")
    if "port" not in smtp:
        raise ConfigError(f"{name}: missing key 'smtp.port'")
    port = smtp["port"]
    if type(port) is not int:
        raise ConfigError(f"{name}: 'smtp.port' must be an integer")
    if port not in (465, 587):
        raise ConfigError(f"{name}: 'smtp.port' must be 465 or 587")

    from_addr = _string(mail, name, "mail", "from")
    reply_to = _string(mail, name, "mail", "reply_to")
    envelope_from = _string(mail, name, "mail", "envelope_from")
    event_line = _string(mail, name, "mail", "event_line") if "event_line" in mail else ""

    if not valid_email(parseaddr(from_addr)[1]):
        raise ConfigError(f"{name}: 'mail.from' has no valid address")
    for key, value in (("reply_to", reply_to), ("envelope_from", envelope_from)):
        if not valid_email(value):
            raise ConfigError(f"{name}: 'mail.{key}' is not a valid address")

    return (
        SmtpConfig(host=host, port=port, username=username),
        MailConfig(
            from_addr=from_addr,
            reply_to=reply_to,
            envelope_from=envelope_from,
            event_line=event_line,
        ),
    )


def load_import(path: Path) -> tuple[int, dict[str, str]]:
    """Load an earlier draw to import: ``year`` and a ``[pairs]`` table of giver = recipient.

    Messages name only IDs, never a match.
    """
    name = path.name
    data = _read_toml(path)
    if set(data) != {"year", "pairs"}:
        raise ConfigError(f"{name}: needs exactly 'year' and a [pairs] table")
    year = data["year"]
    if type(year) is not int:
        raise ConfigError(f"{name}: 'year' must be an integer")
    pairs = data["pairs"]
    if not isinstance(pairs, dict):
        raise ConfigError(f"{name}: 'pairs' must be a table of giver = recipient")
    for giver, recipient in pairs.items():
        if not ID_PATTERN.fullmatch(giver):
            raise ConfigError(f"{name}: a giver ID isn't 1-32 characters of a-z, 0-9 or -")
        if not isinstance(recipient, str) or not ID_PATTERN.fullmatch(recipient):
            raise ConfigError(f"{name}: {giver}: recipient must be a participant ID")
        if giver == recipient:
            raise ConfigError(f"{name}: {giver}: gives to themselves")
    ids = set(pairs)
    extra = sorted(set(pairs.values()) - ids)
    if extra:
        raise ConfigError(f"{name}: {', '.join(extra)}: recipient but not a giver")
    missing = sorted(ids - set(pairs.values()))
    if missing:
        raise ConfigError(f"{name}: {', '.join(missing)}: never a recipient")
    if len(ids) < MIN_PARTICIPANTS:
        raise ConfigError(f"{name}: at least {MIN_PARTICIPANTS} givers are needed")
    return year, dict(pairs)
