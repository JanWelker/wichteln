"""Counting and uniformly picking valid draws. Pure functions."""

from __future__ import annotations

import random
from functools import cache

from wichteln import rules
from wichteln.model import LEVELS, Draw, Participant, Relaxation, State

MIN_PARTICIPANTS = 2
MAX_PARTICIPANTS = 10

Forbidden = set[tuple[str, str]]


def _prepare(ids: list[str], forbidden: Forbidden):
    allowed = {g: sorted(r for r in ids if r != g and (g, r) not in forbidden) for g in ids}
    givers = sorted(ids, key=lambda g: (len(allowed[g]), g))

    @cache
    def count(i: int, used: frozenset[str]) -> int:
        if i == len(givers):
            return 1
        total = 0
        for r in allowed[givers[i]]:
            if r not in used:
                total += count(i + 1, used | {r})
        return total

    return givers, allowed, count


def count_assignments(ids: list[str], forbidden: Forbidden) -> int:
    _, _, count = _prepare(ids, forbidden)
    return count(0, frozenset())


def nth_assignment(ids: list[str], forbidden: Forbidden, n: int) -> dict[str, str]:
    givers, allowed, count = _prepare(ids, forbidden)
    used: frozenset[str] = frozenset()
    acc: dict[str, str] = {}
    for i, g in enumerate(givers):
        for r in allowed[g]:
            if r in used:
                continue
            c = count(i + 1, used | {r})
            if n < c:
                acc[g] = r
                used = used | {r}
                break
            n -= c
        else:
            raise AssertionError("index out of range")  # pragma: no cover
    return acc


def solve(ids: list[str], forbidden: Forbidden, rng: random.Random) -> dict[str, str] | None:
    total = count_assignments(ids, forbidden)
    if total == 0:
        return None
    return nth_assignment(ids, forbidden, rng.randrange(total))


def solve_with_relaxation(
    ids: list[str], history: list[Draw], rng: random.Random
) -> tuple[dict[str, str], Relaxation]:
    if not MIN_PARTICIPANTS <= len(ids) <= MAX_PARTICIPANTS:
        raise ValueError("participant count out of range")
    for level in LEVELS:
        result = solve(ids, rules.forbidden_pairs(history, level), rng)
        if result is not None:
            return result, level
    raise AssertionError("both_draws always has a solution")  # pragma: no cover


def build_draw(
    state: State,
    year: int,
    participants: dict[str, Participant],
    voided: Draw | None,
    event_line: str,
    rng: random.Random,
    now: str,
) -> Draw:
    k = 1 + sum(1 for d in state.draws if d.year == year)
    pairs, relaxed = solve_with_relaxation(sorted(participants), state.history_before(year), rng)
    replaces: dict[str, str] = {}
    if voided is not None:
        for g in participants:
            record = voided.sends.get(g)
            if record is not None and record.accepted_at:
                replaces[g] = record.accepted_at
            elif g in voided.replaces:
                replaces[g] = voided.replaces[g]
    return Draw(
        draw_id=f"{year}-{k}",
        year=year,
        status="final",
        relaxed=relaxed,
        created_at=now,
        participants=dict(participants),
        pairs=pairs,
        event_line=event_line,
        replaces=replaces,
        sends={},
    )
