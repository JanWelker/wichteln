"""Forbidden matches per relaxation level. Pure functions."""

from __future__ import annotations

from wichteln.model import LEVELS, Draw, Relaxation

__all__ = ["LEVELS", "forbidden_pairs"]


def forbidden_pairs(history: list[Draw], level: Relaxation) -> set[tuple[str, str]]:
    """Return the directed matches forbidden at ``level``.

    ``history`` is newest first. Self-matches aren't included; the solver always
    excludes them.
    """
    forbidden: set[tuple[str, str]] = set()
    if level != "both_draws" and len(history) >= 1:
        forbidden |= set(history[0].pairs.items())
    if level == "none" and len(history) >= 2:
        forbidden |= set(history[1].pairs.items())
    return forbidden
