import re

import pytest

from tests.conftest import accepted, make_draw, make_state
from wichteln.errors import StateError
from wichteln.model import ID_PATTERN, SendRecord, from_dict, now_utc, to_dict


@pytest.mark.parametrize("value", ["p1", "a-b", "a" * 32])
def test_id_pattern_accepts(value):
    assert ID_PATTERN.fullmatch(value)


@pytest.mark.parametrize("value", ["P1", "", "a_b", "p1\n", "a" * 33])
def test_id_pattern_rejects(value):
    assert not ID_PATTERN.fullmatch(value)


def sample_state():
    void = make_draw({"p1": "p2", "p2": "p3", "p3": "p1"}, status="void", sends={"p1": accepted()})
    final = make_draw(
        {"p1": "p3", "p3": "p2", "p2": "p1"},
        draw_id="2026-2",
        relaxed="older_draw",
        replaces={"p1": "2026-11-20T19:02:11Z"},
        sends={
            "p1": accepted("2026-11-21T10:00:00Z"),
            "p2": SendRecord("failed", "2026-11-21T10:00:01Z", "2026-11-20T19:02:12Z"),
        },
    )
    return make_state(void, final)


def test_round_trip():
    state = sample_state()
    assert from_dict(to_dict(state)) == state


@pytest.mark.parametrize("fmt", [2, True, "1"])
def test_unsupported_format(fmt):
    data = to_dict(sample_state())
    data["format"] = fmt
    with pytest.raises(StateError, match="unsupported state format"):
        from_dict(data)


def _mutate(fn):
    data = to_dict(sample_state())
    fn(data["draws"][1])
    return data


@pytest.mark.parametrize(
    "mutation",
    [
        lambda d: d.update(status="done"),
        lambda d: d.update(relaxed="x"),
        lambda d: d.update(year="2026"),
        lambda d: d["participants"].update(P1={"name": "X", "email": "x@example.org"}),
        lambda d: d["sends"].update(p9={"result": "accepted", "at": "t", "accepted_at": "t"}),
        lambda d: d["sends"]["p1"].update(result="bounced"),
        lambda d: d["pairs"].update(p1="p1"),
    ],
)
def test_invalid_values(mutation):
    with pytest.raises(ValueError):
        from_dict(_mutate(mutation))


def test_missing_and_wrong_types():
    with pytest.raises(KeyError):
        from_dict(_mutate(lambda d: d.pop("status")))
    with pytest.raises(TypeError):
        from_dict(_mutate(lambda d: d.update(participants=[])))
    with pytest.raises(TypeError):
        from_dict(_mutate(lambda d: d.update(event_line=5)))
    with pytest.raises(TypeError):
        from_dict([])
    with pytest.raises(TypeError):
        from_dict({"format": 1, "draws": {}})


def test_pending():
    draw = make_draw(
        {"p1": "p2", "p2": "p3", "p3": "p1"},
        sends={"p2": accepted(), "p3": SendRecord("failed", "t", None)},
    )
    assert draw.pending() == ["p1", "p3"]


def test_history_and_latest():
    cycle = {"p1": "p2", "p2": "p1"}
    d24 = make_draw(cycle, draw_id="2024-1", year=2024)
    d25v = make_draw(cycle, draw_id="2025-1", year=2025, status="void")
    d25 = make_draw(cycle, draw_id="2025-2", year=2025)
    d26 = make_draw(cycle, draw_id="2026-1", year=2026)
    d27v = make_draw(cycle, draw_id="2027-1", year=2027, status="void")
    state = make_state(d24, d25v, d25, d26, d27v)
    assert state.history_before(2026) == [d25, d24]
    assert state.history_before(2024) == []
    assert state.latest_final() is d26
    assert state.current(2025) is d25
    assert state.current(2027) is None
    assert make_state().latest_final() is None


def test_now_utc():
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", now_utc())


def test_imported_flag():
    state = make_state(make_draw({"p1": "p2", "p2": "p1"}))
    state.draws[0].imported = True
    assert from_dict(to_dict(state)).draws[0].imported is True
    data = to_dict(state)
    del data["draws"][0]["imported"]
    assert from_dict(data).draws[0].imported is False
    data["draws"][0]["imported"] = "yes"
    with pytest.raises(ValueError):
        from_dict(data)
