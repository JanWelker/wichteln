"""Data types and the conversion of the state to and from JSON."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

from wichteln.errors import StateError

ID_PATTERN = re.compile(r"[a-z0-9-]{1,32}")

Relaxation = Literal["none", "older_draw", "both_draws"]
LEVELS: tuple[Relaxation, ...] = ("none", "older_draw", "both_draws")
STATUSES = ("final", "void")
RESULTS = ("accepted", "failed")


@dataclass(frozen=True)
class Participant:
    id: str
    name: str
    email: str


@dataclass(frozen=True)
class SmtpConfig:
    host: str
    port: int
    username: str


@dataclass(frozen=True)
class MailConfig:
    from_addr: str
    reply_to: str
    envelope_from: str
    event_line: str


@dataclass(frozen=True)
class SendRecord:
    result: Literal["accepted", "failed"]
    at: str
    accepted_at: str | None


@dataclass
class Draw:
    draw_id: str
    year: int
    status: Literal["final", "void"]
    relaxed: Relaxation
    created_at: str
    participants: dict[str, Participant]
    pairs: dict[str, str]
    event_line: str
    replaces: dict[str, str] = field(default_factory=dict)
    sends: dict[str, SendRecord] = field(default_factory=dict)
    imported: bool = False

    def pending(self) -> list[str]:
        return sorted(
            g for g in self.participants if g not in self.sends or self.sends[g].result == "failed"
        )


@dataclass
class State:
    format: int = 1
    draws: list[Draw] = field(default_factory=list)

    def current(self, year: int) -> Draw | None:
        for d in self.draws:
            if d.status == "final" and d.year == year:
                return d
        return None

    def latest_final(self) -> Draw | None:
        finals = [d for d in self.draws if d.status == "final"]
        if not finals:
            return None
        return max(finals, key=lambda d: d.year)

    def history_before(self, year: int) -> list[Draw]:
        finals = [d for d in self.draws if d.status == "final" and d.year < year]
        return sorted(finals, key=lambda d: d.year, reverse=True)


def now_utc() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def to_dict(state: State) -> dict[str, Any]:
    return {
        "format": state.format,
        "draws": [
            {
                "draw_id": d.draw_id,
                "year": d.year,
                "status": d.status,
                "relaxed": d.relaxed,
                "created_at": d.created_at,
                "participants": {
                    pid: {"name": p.name, "email": p.email} for pid, p in d.participants.items()
                },
                "pairs": dict(d.pairs),
                "event_line": d.event_line,
                "replaces": dict(d.replaces),
                "sends": {
                    g: {"result": s.result, "at": s.at, "accepted_at": s.accepted_at}
                    for g, s in d.sends.items()
                },
                "imported": d.imported,
            }
            for d in state.draws
        ],
    }


def _str(value: Any) -> str:
    if type(value) is not str:
        raise TypeError("expected str")
    return value


def _opt_str(value: Any) -> str | None:
    return None if value is None else _str(value)


def _dict(value: Any) -> dict:
    if type(value) is not dict:
        raise TypeError("expected object")
    return value


def _draw_from_dict(data: dict[str, Any]) -> Draw:
    data = _dict(data)
    status = data["status"]
    if status not in STATUSES:
        raise ValueError("unknown status")
    relaxed = data["relaxed"]
    if relaxed not in LEVELS:
        raise ValueError("unknown relaxation level")
    year = data["year"]
    if type(year) is not int:
        raise ValueError("year is not an int")
    imported = data.get("imported", False)
    if type(imported) is not bool:
        raise ValueError("imported is not a bool")

    participants: dict[str, Participant] = {}
    for pid, p in _dict(data["participants"]).items():
        if not ID_PATTERN.fullmatch(pid):
            raise ValueError("bad participant id")
        p = _dict(p)
        participants[pid] = Participant(id=pid, name=_str(p["name"]), email=_str(p["email"]))

    pairs = {_str(g): _str(r) for g, r in _dict(data["pairs"]).items()}
    replaces = {_str(g): _str(t) for g, t in _dict(data["replaces"]).items()}
    sends: dict[str, SendRecord] = {}
    for g, s in _dict(data["sends"]).items():
        s = _dict(s)
        if s["result"] not in RESULTS:
            raise ValueError("unknown send result")
        sends[g] = SendRecord(
            result=s["result"], at=_str(s["at"]), accepted_at=_opt_str(s["accepted_at"])
        )

    for mapping in (pairs, sends, replaces):
        if any(k not in participants for k in mapping):
            raise ValueError("key not in snapshot")
    if status == "final":
        ids = set(participants)
        if set(pairs) != ids or set(pairs.values()) != ids or any(g == r for g, r in pairs.items()):
            raise ValueError("pairs are not a valid draw")

    return Draw(
        draw_id=_str(data["draw_id"]),
        year=year,
        status=status,
        relaxed=relaxed,
        created_at=_str(data["created_at"]),
        participants=participants,
        pairs=pairs,
        event_line=_str(data["event_line"]),
        replaces=replaces,
        sends=sends,
        imported=imported,
    )


def from_dict(data: Any) -> State:
    if not isinstance(data, dict):
        raise TypeError("expected object")
    fmt = data.get("format")
    if type(fmt) is not int or fmt != 1:
        raise StateError("unsupported state format")
    draws = data["draws"]
    if type(draws) is not list:
        raise TypeError("expected list")
    return State(format=1, draws=[_draw_from_dict(d) for d in draws])
