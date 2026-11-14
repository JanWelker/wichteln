import json
import os

import pytest
from cryptography.fernet import Fernet

from tests.conftest import accepted, make_draw, make_state
from wichteln import store
from wichteln.errors import StateError
from wichteln.model import Participant, to_dict


@pytest.fixture
def key():
    return Fernet.generate_key()


def sample():
    return make_state(make_draw({"p1": "p2", "p2": "p1"}, sends={"p1": accepted()}))


def write_raw(dir, key, payload: bytes):
    (dir / "state.enc").write_bytes(Fernet(key).encrypt(payload))


def test_round_trip(data_dir, key):
    store.save(data_dir, key, sample())
    assert store.exists(data_dir)
    assert store.load(data_dir, key) == sample()


def test_encrypted_on_disk(data_dir, key):
    state = sample()
    draw = state.draws[0]
    draw.participants["p1"] = Participant("p1", "participantmarkerxyz", "x@example.org")
    store.save(data_dir, key, state)
    assert b"participantmarkerxyz" not in (data_dir / "state.enc").read_bytes()


def test_wrong_key(data_dir, key):
    store.save(data_dir, key, sample())
    with pytest.raises(StateError, match="cannot decrypt"):
        store.load(data_dir, Fernet.generate_key())


def test_invalid_key(data_dir, key):
    store.save(data_dir, key, sample())
    with pytest.raises(StateError, match="invalid key format"):
        store.load(data_dir, b"0123456789")


def test_non_json(data_dir, key):
    write_raw(data_dir, key, b"not json")
    with pytest.raises(StateError, match="malformed state"):
        store.load(data_dir, key)


def test_missing_status(data_dir, key):
    data = to_dict(sample())
    del data["draws"][0]["status"]
    write_raw(data_dir, key, json.dumps(data).encode())
    with pytest.raises(StateError, match="malformed state"):
        store.load(data_dir, key)


def test_bad_format(data_dir, key):
    data = to_dict(sample())
    data["format"] = 2
    write_raw(data_dir, key, json.dumps(data).encode())
    with pytest.raises(StateError, match="unsupported state format"):
        store.load(data_dir, key)


def test_missing_file(data_dir, key):
    assert not store.exists(data_dir)
    with pytest.raises(StateError, match="--no-history"):
        store.load(data_dir, key)


def test_crash_before_replace(data_dir, key, monkeypatch):
    store.save(data_dir, key, sample())

    def boom(*args):
        raise RuntimeError("crash")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(RuntimeError):
        store.save(data_dir, key, make_state())
    monkeypatch.undo()
    assert store.load(data_dir, key) == sample()


def test_file_mode(data_dir, key):
    store.save(data_dir, key, sample())
    assert (data_dir / "state.enc").stat().st_mode & 0o777 == 0o600


def test_stale_tmp(data_dir, key):
    tmp = data_dir / "state.enc.tmp"
    tmp.write_bytes(b"stale")
    tmp.chmod(0o644)
    store.save(data_dir, key, sample())
    assert not tmp.exists()
    assert (data_dir / "state.enc").stat().st_mode & 0o777 == 0o600
    assert store.load(data_dir, key) == sample()
