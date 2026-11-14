import pytest

from wichteln.splice import splice_out

CYCLE = {"p1": "p2", "p2": "p3", "p3": "p4", "p4": "p5", "p5": "p1"}


def test_splice_in_cycle():
    result = splice_out(CYCLE, "p3", set())
    assert result == {"p1": "p2", "p2": "p4", "p4": "p5", "p5": "p1"}
    changed = [g for g in result if result[g] != CYCLE[g]]
    assert changed == ["p2"]
    assert "p3" not in result and "p3" not in result.values()


def test_mutual_pair():
    assert splice_out({"p1": "p2", "p2": "p1", "p3": "p4", "p4": "p3"}, "p2", set()) is None


def test_forbidden():
    assert splice_out(CYCLE, "p3", {("p2", "p4")}) is None


def test_unknown_dropout():
    with pytest.raises(KeyError):
        splice_out(CYCLE, "p9", set())
