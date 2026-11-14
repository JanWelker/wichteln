import subprocess

import pytest
from cryptography.fernet import Fernet

from wichteln import keychain
from wichteln.errors import StateError

pytestmark = pytest.mark.real_keychain


class FakeRun:
    def __init__(self, results):
        self.results = list(results)
        self.calls = []

    def __call__(self, args, **kwargs):
        self.calls.append((args, kwargs))
        code, out = self.results.pop(0)
        return subprocess.CompletedProcess(args, code, stdout=out, stderr="")


@pytest.fixture
def run(monkeypatch):
    def install(*results):
        fake = FakeRun(results)
        monkeypatch.setattr(subprocess, "run", fake)
        return fake

    return install


def test_get_secret(run):
    fake = run((0, "secret\n"))
    assert keychain.get_secret("smtp") == "secret"
    args, kwargs = fake.calls[0]
    assert args == [
        "/usr/bin/security",
        "find-generic-password",
        "-s",
        "wichteln",
        "-a",
        "smtp",
        "-w",
    ]
    assert "shell" not in kwargs
    assert kwargs["capture_output"] is True


def test_get_secret_missing(run):
    run((44, ""))
    with pytest.raises(
        keychain.SecretMissing, match="restore it with: security add-generic-password"
    ):
        keychain.get_secret("fernet-key")


def test_get_secret_other_error(run):
    run((51, ""))
    with pytest.raises(StateError) as exc:
        keychain.get_secret("smtp")
    assert "51" in str(exc.value)
    assert "restore" not in str(exc.value)


def test_store_key(run):
    key = Fernet.generate_key().decode("ascii")
    fake = run((0, ""), (0, key + "\n"))
    keychain.store_fernet_key(key)
    args, kwargs = fake.calls[0]
    assert args == ["/usr/bin/security", "-i"]
    assert key in kwargs["input"]
    for call_args, _ in fake.calls:
        assert call_args[0] == "/usr/bin/security"
        assert key not in " ".join(call_args)


def test_store_key_mismatch(run):
    key = Fernet.generate_key().decode("ascii")
    run((0, ""), (0, "other\n"))
    with pytest.raises(StateError, match="storing the key in the Keychain failed"):
        keychain.store_fernet_key(key)


def test_store_key_not_found(run):
    key = Fernet.generate_key().decode("ascii")
    run((0, ""), (44, ""))
    with pytest.raises(StateError, match="storing the key in the Keychain failed"):
        keychain.store_fernet_key(key)


@pytest.mark.parametrize("value", ["short", Fernet.generate_key().decode("ascii") + "\n", "a b"])
def test_store_key_rejects(run, value):
    fake = run()
    with pytest.raises(ValueError):
        keychain.store_fernet_key(value)
    assert fake.calls == []
