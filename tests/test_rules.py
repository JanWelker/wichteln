from tests.conftest import make_draw
from wichteln.rules import LEVELS, forbidden_pairs

NEWER = make_draw({"p1": "p2", "p2": "p3", "p3": "p1"}, draw_id="2025-1", year=2025)
OLDER = make_draw({"p1": "p3", "p3": "p2", "p2": "p1"}, draw_id="2024-1", year=2024)


def test_two_draws():
    history = [NEWER, OLDER]
    assert forbidden_pairs(history, "none") == set(NEWER.pairs.items()) | set(OLDER.pairs.items())
    assert forbidden_pairs(history, "older_draw") == set(NEWER.pairs.items())
    assert forbidden_pairs(history, "both_draws") == set()


def test_one_draw():
    assert forbidden_pairs([NEWER], "none") == set(NEWER.pairs.items())
    assert forbidden_pairs([NEWER], "older_draw") == set(NEWER.pairs.items())
    assert forbidden_pairs([NEWER], "both_draws") == set()


def test_no_history():
    for level in LEVELS:
        assert forbidden_pairs([], level) == set()
