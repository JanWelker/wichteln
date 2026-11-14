import random
import time

import pytest

from wichteln import cli, keychain
from wichteln.errors import StateError
from wichteln.mailer import TransportError
from wichteln.model import Draw, Participant, SendRecord, State

NAMES = ["Alma", "Bert", "Cleo", "Dora", "Emil", "Fritz", "Gina", "Hugo", "Ines", "Jonas", "Kurt"]


@pytest.fixture(autouse=True)
def pinned_tz(monkeypatch):
    monkeypatch.setenv("TZ", "Europe/Zurich")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


def participants(n):
    """IDs p1..pn with names that share no substring with any ID."""
    return {
        f"p{i}": Participant(
            id=f"p{i}", name=NAMES[i - 1], email=f"{NAMES[i - 1].lower()}@example.org"
        )
        for i in range(1, n + 1)
    }


def make_draw(
    pairs,
    *,
    draw_id="2026-1",
    year=2026,
    status="final",
    relaxed="none",
    created_at="2026-11-20T19:02:05Z",
    event_line="Bescherung am 24.12.",
    replaces=None,
    sends=None,
    people=None,
):
    ids = set(pairs) | set(pairs.values())
    people = people or participants(max(int(i[1:]) for i in ids))
    snapshot = {pid: p for pid, p in people.items() if pid in ids}
    return Draw(
        draw_id=draw_id,
        year=year,
        status=status,
        relaxed=relaxed,
        created_at=created_at,
        participants=snapshot,
        pairs=dict(pairs),
        event_line=event_line,
        replaces=dict(replaces or {}),
        sends=dict(sends or {}),
    )


def make_state(*draws):
    return State(format=1, draws=list(draws))


def accepted(at="2026-11-20T19:02:11Z"):
    return SendRecord(result="accepted", at=at, accepted_at=at)


# --- Phase 3 fixtures -------------------------------------------------------


@pytest.fixture(autouse=True)
def data_dir(tmp_path, monkeypatch):
    path = tmp_path / "data"
    path.mkdir()
    monkeypatch.setenv("WICHTELN_HOME", str(path))
    return path


class FakeKeychain:
    def __init__(self):
        self.items = {"smtp": "test-password"}
        self.fail_write = False

    def get_secret(self, account):
        if account not in self.items:
            raise keychain.SecretMissing(
                f"Keychain item {account} missing; restore it with: "
                f"security add-generic-password -s wichteln -a {account} -U -w"
            )
        return self.items[account]

    def store_fernet_key(self, key):
        if self.fail_write:
            raise StateError("storing the key in the Keychain failed")
        self.items["fernet-key"] = key


@pytest.fixture(autouse=True)
def fake_keychain(request, monkeypatch):
    if request.node.get_closest_marker("real_keychain"):
        return None
    fake = FakeKeychain()
    monkeypatch.setattr(keychain, "get_secret", fake.get_secret)
    monkeypatch.setattr(keychain, "store_fernet_key", fake.store_fernet_key)
    return fake


# --- Phase 4 fixtures -------------------------------------------------------


class FakeTransport:
    def __init__(self):
        self.sent = []
        self.logins = 0
        self.closes = 0
        self.login_error = None
        self.refuse = set()
        self.disconnect_after = None

    def login(self):
        self.logins += 1
        if self.login_error is not None:
            raise self.login_error

    def send(self, msg):
        if self.disconnect_after is not None and len(self.sent) >= self.disconnect_after:
            raise TransportError("connect", None, "SMTPServerDisconnected")
        if msg["To"] in self.refuse:
            raise TransportError("send", 550, "SMTPRecipientsRefused")
        self.sent.append(msg)

    def close(self):
        self.closes += 1

    def fail_login(self, step="connect", code=None):
        self.login_error = TransportError(
            step, code, "SMTPAuthenticationError" if code else "OSError"
        )


@pytest.fixture
def fake_transport():
    return FakeTransport()


# --- Phase 5 fixtures -------------------------------------------------------


@pytest.fixture(autouse=True)
def rng(monkeypatch):
    holder = {"seed": 1}
    monkeypatch.setattr(cli, "make_rng", lambda: random.Random(holder["seed"]))
    return holder


class Answers:
    def __init__(self):
        self.queue = []
        self.questions = []

    def __call__(self, question):
        self.questions.append(question)
        return self.queue.pop(0) if self.queue else False


@pytest.fixture(autouse=True)
def answers(monkeypatch):
    fake = Answers()
    monkeypatch.setattr(cli, "confirm", fake)
    return fake


class Year:
    value = 2026


@pytest.fixture(autouse=True)
def year(monkeypatch):
    holder = Year()
    monkeypatch.setattr(cli, "current_year", lambda: holder.value)
    return holder


@pytest.fixture(autouse=True)
def wire_transport(monkeypatch, fake_transport):
    monkeypatch.setattr(cli, "make_transport", lambda *args: fake_transport)


def assert_no_name_leak(output, state=None, allowed=None):
    names = set(NAMES)
    if state is not None:
        for draw in state.draws:
            names |= {p.name for p in draw.participants.values()}
    names.discard(allowed)
    for line in output.splitlines():
        for name in names:
            assert name not in line, f"name leaked in output line: {line!r}"
