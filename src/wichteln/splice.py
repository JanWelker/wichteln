"""Reconnecting the chain around a dropout. Pure function."""

from __future__ import annotations


def splice_out(
    pairs: dict[str, str], dropout: str, forbidden: set[tuple[str, str]]
) -> dict[str, str] | None:
    """Return the pairs without ``dropout`` and with G → R, or None if not allowed.

    Raises KeyError for an unknown dropout.
    """
    recipient = pairs[dropout]
    giver = next(g for g, r in pairs.items() if r == dropout)
    if giver == recipient or (giver, recipient) in forbidden:
        return None
    result = {g: r for g, r in pairs.items() if g != dropout}
    result[giver] = recipient
    return result
