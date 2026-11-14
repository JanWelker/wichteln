import random
import time
from collections import Counter

import pytest

from tests.conftest import accepted, make_draw, make_state, participants
from wichteln.model import SendRecord
from wichteln.solver import (
    build_draw,
    count_assignments,
    nth_assignment,
    solve,
    solve_with_relaxation,
)


def ids(n):
    return [f"p{i}" for i in range(1, n + 1)]


@pytest.mark.parametrize(
    "n,expected", [(2, 1), (3, 2), (4, 9), (5, 44), (6, 265), (7, 1854), (8, 14833)]
)
def test_derangement_counts(n, expected):
    assert count_assignments(ids(n), set()) == expected


def test_random_cases():
    for seed in range(1000):
        rng = random.Random(seed)
        people = ids(rng.randint(2, 8))
        forbidden = {(g, r) for g in people for r in people if g != r and rng.random() < 0.3}
        result = solve(people, forbidden, rng)
        if result is None:
            assert count_assignments(people, forbidden) == 0
            continue
        assert sorted(result) == people
        assert sorted(result.values()) == people
        for g, r in result.items():
            assert g != r
            assert (g, r) not in forbidden


def test_impossible():
    forbidden = {("p1", "p2"), ("p2", "p3"), ("p3", "p1"), ("p1", "p3"), ("p3", "p2"), ("p2", "p1")}
    assert solve(ids(3), forbidden, random.Random(1)) is None


def test_relaxation_levels():
    rng = random.Random(1)
    newer = make_draw({"p1": "p2", "p2": "p3", "p3": "p1"}, year=2025)
    older = make_draw({"p1": "p3", "p3": "p2", "p2": "p1"}, year=2024)
    # Older draw forbids the other cycle; with both, nothing is left.
    pairs, level = solve_with_relaxation(ids(3), [newer, older], rng)
    assert level == "older_draw"
    assert pairs == older.pairs
    # Same cycle twice: only both_draws works.
    pairs, level = solve_with_relaxation(ids(2), [make_draw({"p1": "p2", "p2": "p1"})], rng)
    assert level == "both_draws"
    assert pairs == {"p1": "p2", "p2": "p1"}
    _, level = solve_with_relaxation(ids(4), [], rng)
    assert level == "none"


@pytest.mark.parametrize("n", [1, 11])
def test_relaxation_size_limits(n):
    with pytest.raises(ValueError):
        solve_with_relaxation(ids(n), [], random.Random(1))


def test_uniformity():
    rng = random.Random(1)
    counts = Counter(tuple(sorted(solve(ids(4), set(), rng).items())) for _ in range(9000))
    assert len(counts) == 9
    for c in counts.values():
        assert 850 <= c <= 1150


def test_nth_covers_all():
    people = ids(5)
    seen = {tuple(sorted(nth_assignment(people, set(), n).items())) for n in range(44)}
    assert len(seen) == 44


def test_performance():
    start = time.perf_counter()
    total = count_assignments(ids(10), set())
    nth_assignment(ids(10), set(), total - 1)
    assert total == 1334961
    assert time.perf_counter() - start < 2


def test_build_draw_id_counts_void_and_final():
    void = make_draw({"p1": "p2", "p2": "p1"}, status="void")
    final = make_draw({"p1": "p2", "p2": "p1"}, draw_id="2026-2")
    other = make_draw({"p1": "p2", "p2": "p1"}, draw_id="2025-1", year=2025)
    state = make_state(other, void, final)
    draw = build_draw(state, 2026, participants(3), None, "", random.Random(1), "now")
    assert draw.draw_id == "2026-3"
    assert draw.status == "final"
    assert draw.created_at == "now"
    assert draw.sends == {}
    assert draw.replaces == {}


def test_build_draw_replaces_and_relaxation():
    voided = make_draw(
        {"p1": "p2", "p2": "p3", "p3": "p4", "p4": "p1"},
        status="void",
        relaxed="both_draws",
        replaces={"p2": "2026-11-01T10:00:00Z", "p3": "2026-11-02T10:00:00Z", "p4": "x"},
        sends={
            "p1": accepted("2026-11-20T19:02:11Z"),
            "p2": SendRecord("failed", "2026-11-21T10:00:00Z", "2026-11-20T19:02:12Z"),
            "p3": SendRecord("failed", "2026-11-21T10:00:00Z", None),
        },
    )
    people = {k: v for k, v in participants(4).items() if k != "p4"}
    draw = build_draw(make_state(voided), 2026, people, voided, "Fest", random.Random(1), "now")
    assert draw.replaces == {
        "p1": "2026-11-20T19:02:11Z",
        "p2": "2026-11-20T19:02:12Z",
        "p3": "2026-11-02T10:00:00Z",
    }
    assert draw.relaxed == "none"
    assert draw.event_line == "Fest"
    assert set(draw.participants) == {"p1", "p2", "p3"}
