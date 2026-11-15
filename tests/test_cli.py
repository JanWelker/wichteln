import shutil

import pytest
from cryptography.fernet import Fernet

from tests.conftest import NAMES, accepted, assert_no_name_leak, make_draw, make_state
from wichteln import cli, solver, store
from wichteln.cli import confirm as real_confirm
from wichteln.errors import StateError
from wichteln.model import SendRecord


class Runner:
    def __init__(self, capsys, data_dir, keychain):
        self.capsys = capsys
        self.data_dir = data_dir
        self.keychain = keychain

    def __call__(self, *argv, allowed=None):
        code = cli.main(list(argv))
        captured = self.capsys.readouterr()
        self.out, self.err = captured.out, captured.err
        try:
            state = self.state() if self.has_state() else None
        except StateError:
            state = None
        assert_no_name_leak(self.out + self.err, state, allowed)
        return code

    def key(self):
        return self.keychain.items["fernet-key"].encode()

    def has_state(self):
        return store.exists(self.data_dir) and "fernet-key" in self.keychain.items

    def state(self):
        return store.load(self.data_dir, self.key())

    def save(self, state):
        store.save(self.data_dir, self.key(), state)

    def write_participants(self, n=4, emails=None):
        emails = emails or {}
        text = ""
        for i in range(1, n + 1):
            pid = f"p{i}"
            email = emails.get(pid, f"{NAMES[i - 1].lower()}@example.org")
            text += f'[[participant]]\nid = "{pid}"\nname = "{NAMES[i - 1]}"\nemail = "{email}"\n\n'
        (self.data_dir / "participants.toml").write_text(text)

    def write_config(self, event_line="Bescherung am 24.12."):
        (self.data_dir / "config.toml").write_text(
            '[smtp]\nhost = "smtp.example.org"\nport = 465\nusername = "w@example.org"\n'
            '[mail]\nfrom = "Wichteln <w@example.org>"\nreply_to = "w@example.org"\n'
            f'envelope_from = "w@example.org"\nevent_line = "{event_line}"\n'
        )

    def setup(self, n=4):
        assert self("init") == 0
        self.write_participants(n)
        self.write_config()


@pytest.fixture
def run(capsys, data_dir, fake_keychain):
    return Runner(capsys, data_dir, fake_keychain)


@pytest.fixture
def drawn(run, fake_transport):
    run.setup()
    assert run("draw") == 0
    fake_transport.sent.clear()
    return run


def bodies(transport):
    return {m["To"]: m.get_content() for m in transport.sent}


def save_draw(run, pairs, n=4, **kwargs):
    """Replace the state with one final draw with fixed pairs."""
    draw = make_draw(pairs, **kwargs)
    run.save(make_state(draw))
    run.write_participants(n)
    return draw


# --- init ---------------------------------------------------------------------


def test_init_then_draw(run, fake_transport):
    run.setup()
    assert run("draw") == 0
    assert len(fake_transport.sent) == 4
    state = run.state()
    assert [d.status for d in state.draws] == ["final"]
    assert "sent 4 of 4" in run.out
    assert "history: none" in run.out
    assert "relaxation: none" in run.out


def test_init_prints_key_once(run, fake_keychain):
    assert run("init") == 0
    key = fake_keychain.items["fernet-key"]
    assert key in run.out
    assert (run.data_dir / "participants.toml").exists()
    assert (run.data_dir / "config.toml").exists()
    before = (run.data_dir / "participants.toml").read_text() + "x"
    (run.data_dir / "participants.toml").write_text(before)
    state_bytes = (run.data_dir / "state.enc").read_bytes()
    assert run("init") == 0
    assert key not in run.out
    assert "nothing to do: key and state.enc exist" in run.out
    assert (run.data_dir / "participants.toml").read_text() == before
    assert (run.data_dir / "state.enc").read_bytes() == state_bytes


def test_init_state_without_key(run, fake_keychain):
    run("init")
    del fake_keychain.items["fernet-key"]
    assert run("init") == 3
    assert "security add-generic-password" in run.err


def test_init_key_without_state(run):
    run("init")
    (run.data_dir / "state.enc").unlink()
    assert run("init") == 3
    assert "state.enc missing" in run.err


def test_init_keychain_write_fails(run, fake_keychain):
    fake_keychain.fail_write = True
    assert run("init") == 3
    assert not (run.data_dir / "state.enc").exists()
    assert "Fernet key" not in run.out
    assert "storing the key in the Keychain failed" in run.err


def test_key_lost_for_good(drawn, fake_keychain, tmp_path):
    shutil.move(drawn.data_dir / "state.enc", tmp_path / "old-state.enc")
    del fake_keychain.items["fernet-key"]
    assert drawn("init") == 0
    assert drawn("draw") == 0
    assert "history: none" in drawn.out


# --- missing key or state -----------------------------------------------------


@pytest.mark.parametrize("command", [["send"], ["dropout", "p1"], ["status"]])
def test_key_without_state(drawn, command):
    (drawn.data_dir / "state.enc").unlink()
    assert drawn(*command) == 3


@pytest.mark.parametrize("command", [["send"], ["dropout", "p1"], ["status"], ["draw"]])
def test_both_missing(run, command):
    run.write_participants()
    run.write_config()
    assert run(*command) == 3
    assert "wichteln init" in run.err


def test_draw_state_without_key(drawn, fake_keychain):
    del fake_keychain.items["fernet-key"]
    assert drawn("draw") == 3


def test_malformed_state(drawn):
    token = Fernet(drawn.key()).encrypt(b'{"format": 1}')
    (drawn.data_dir / "state.enc").write_bytes(token)
    assert drawn("status") == 3
    assert "malformed state" in drawn.err


def test_keychain_locked(drawn, fake_keychain, monkeypatch):
    from wichteln import keychain

    def locked(account):
        raise StateError("keychain access failed (exit 51)")

    monkeypatch.setattr(keychain, "get_secret", locked)
    assert drawn("status") == 3
    assert "keychain access failed" in drawn.err


# --- draw ---------------------------------------------------------------------


def test_draw_without_smtp_password(run, fake_keychain):
    run.setup()
    del fake_keychain.items["smtp"]
    assert run("draw") == 3
    assert run.state().draws == []


def test_draw_broken_config(run):
    run.setup()
    (run.data_dir / "config.toml").write_text("[smtp")
    assert run("draw") == 1
    assert run.state().draws == []


def test_second_draw_refused(drawn, fake_transport):
    assert drawn("draw") == 1
    assert "wichteln send" in drawn.err
    assert fake_transport.sent == []


@pytest.mark.parametrize("answer", [[False], []])
def test_redraw_declined(drawn, answers, answer):
    answers.queue = answer
    assert drawn("draw", "--redraw") == 1
    assert answers.questions == ["Replace draw 2026-1 and email everyone again? [y/N]"]
    assert [d.status for d in drawn.state().draws] == ["final"]


def test_redraw_yes(drawn, fake_transport):
    state = drawn.state()
    first = state.draws[0]
    first.sends["p2"] = SendRecord("failed", "2026-11-20T19:03:00Z", None)
    drawn.save(state)
    assert drawn("draw", "--redraw", "--yes") == 0
    state = drawn.state()
    assert [d.status for d in state.draws] == ["void", "final"]
    assert state.draws[1].draw_id == "2026-2"
    texts = bodies(fake_transport)
    assert "ersetzt" in texts["alma@example.org"]
    assert "ersetzt" not in texts["bert@example.org"]
    assert "Ziehung 2026-2" in texts["bert@example.org"]


def test_redraw_answer_yes(drawn, answers):
    answers.queue = [True]
    assert drawn("draw", "--redraw") == 0


def test_no_history(run):
    run.setup()
    (run.data_dir / "state.enc").unlink()
    assert run("draw") == 3
    assert "--no-history" in run.err
    assert run("draw", "--no-history") == 0
    assert len(run.state().draws) == 1


def test_draw_prints_history(drawn, year):
    year.value = 2027
    assert drawn("draw") == 0
    year.value = 2028
    assert drawn("draw") == 0
    assert "history: 2027-1, 2026-1" in drawn.out
    year.value = 2029
    assert drawn("draw") == 0
    assert "history: 2028-1, 2027-1" in drawn.out


# --- send ---------------------------------------------------------------------


def test_partial_failure_and_resume(run, fake_transport):
    run.setup()
    fake_transport.refuse = {"bert@example.org"}
    assert run("draw") == 2
    assert "sent 3 of 4" in run.out
    assert "p2: send failed (550)" in run.out
    assert run.err.strip().endswith("1 of 4 emails failed")
    fake_transport.refuse = set()
    fake_transport.sent.clear()
    assert run("send") == 0
    assert [m["To"] for m in fake_transport.sent] == ["bert@example.org"]
    assert run("send") == 0
    assert "nothing to send" in run.out


def test_send_broken_config(drawn, fake_transport):
    (drawn.data_dir / "config.toml").write_text("x = ")
    assert drawn("send", "p1") == 1
    assert fake_transport.sent == []


def test_login_failure(run, fake_transport):
    run.setup()
    fake_transport.fail_login("auth", 535)
    assert run("draw") == 2
    assert fake_transport.logins == 1
    assert "sent 0 of 4" in run.out
    assert len(run.state().draws) == 1
    assert run.state().draws[0].pending() == ["p1", "p2", "p3", "p4"]


def test_send_id_same_body(run, fake_transport):
    run.setup()
    run("draw")
    original = bodies(fake_transport)["alma@example.org"]
    fake_transport.sent.clear()
    run.write_config(event_line="Neue Zeile")
    run.write_participants()
    text = (run.data_dir / "participants.toml").read_text().replace('"Alma"', '"Almira"')
    (run.data_dir / "participants.toml").write_text(text)
    assert run("send", "p1") == 0
    assert "sent 1 of 1" in run.out
    assert "draw: 2026-1" in run.out
    assert bodies(fake_transport)["alma@example.org"] == original


def test_changed_address_yes(drawn, answers, fake_transport):
    drawn.write_participants(emails={"p1": "alma.new@example.org"})
    answers.queue = [True]
    assert drawn("send", "p1") == 0
    assert answers.questions == [
        "p1: address changed from alma@example.org to alma.new@example.org. "
        "Send to the new address? [y/N]"
    ]
    assert [m["To"] for m in fake_transport.sent] == ["alma.new@example.org"]
    assert drawn.state().draws[0].participants["p1"].email == "alma.new@example.org"
    answers.questions.clear()
    assert drawn("send", "p1") == 0
    assert answers.questions == []


@pytest.mark.parametrize("answer", [[False], []])
def test_changed_address_no(drawn, answers, fake_transport, answer):
    drawn.write_participants(emails={"p1": "alma.new@example.org"})
    answers.queue = answer
    assert drawn("send", "p1") == 0
    assert [m["To"] for m in fake_transport.sent] == ["alma@example.org"]
    assert "p1: using the address stored in the draw" in drawn.err
    assert drawn.state().draws[0].participants["p1"].email == "alma@example.org"


def test_swapped_addresses(drawn, fake_transport):
    state = drawn.state()
    state.draws[0].sends.clear()
    drawn.save(state)
    drawn.write_participants(emails={"p1": "bert@example.org", "p2": "alma@example.org"})
    assert drawn("send") == 0
    sent = {m["To"]: m.get_content() for m in fake_transport.sent}
    assert "Hallo Alma" in sent["alma@example.org"]
    assert "Hallo Bert" in sent["bert@example.org"]


def test_new_address_failed_send_not_stored(drawn, answers, fake_transport):
    drawn.write_participants(emails={"p1": "alma.new@example.org"})
    answers.queue = [True]
    fake_transport.refuse = {"alma.new@example.org"}
    assert drawn("send", "p1") == 2
    assert drawn.state().draws[0].participants["p1"].email == "alma@example.org"


def test_send_with_bad_participants_file(drawn, fake_transport):
    (drawn.data_dir / "participants.toml").write_text('[[participant]]\nid = "p1"\n')
    assert drawn("send", "p2") == 0
    assert "warning: participants.toml unreadable" in drawn.err
    assert "using addresses from the draw" in drawn.err
    assert [m["To"] for m in fake_transport.sent] == ["bert@example.org"]


def test_send_unknown_id(drawn):
    assert drawn("send", "p9") == 1
    assert "unknown participant p9" in drawn.err


def test_send_nothing_pending(drawn, fake_transport):
    assert drawn("send") == 0
    assert "nothing to send" in drawn.out
    assert fake_transport.sent == []


def test_send_next_year(drawn, year):
    year.value = 2027
    assert drawn("send", "p1") == 0
    assert "draw: 2026-1" in drawn.out


# --- dropout ------------------------------------------------------------------

CYCLE = {"p1": "p2", "p2": "p3", "p3": "p4", "p4": "p1"}
ALL_SENT = {g: accepted() for g in CYCLE}


@pytest.fixture
def cycle(run):
    run.setup()
    return save_draw(run, CYCLE, sends=ALL_SENT)


def test_dropout_splice(cycle, run, answers, fake_transport):
    answers.queue = [True]
    assert run("dropout", "p3") == 0
    assert answers.questions == ["Remove Cleo (p3) from draw 2026-1? [y/N]"]
    assert "spliced; sent 1 of 1" in run.out
    assert [m["To"] for m in fake_transport.sent] == ["bert@example.org"]
    body = fake_transport.sent[0].get_content()
    assert "du beschenkst dieses Jahr: Dora." in body
    assert "ersetzt die E-Mail vom 20.11.2026 um 20:02" in body
    draw = run.state().draws[0]
    assert draw.pairs == {"p1": "p2", "p2": "p4", "p4": "p1"}
    assert "p3" not in draw.participants and "p3" not in draw.replaces
    assert draw.replaces == {"p2": "2026-11-20T19:02:11Z"}


def test_dropout_question_names_only_dropout(cycle, run, answers):
    answers.queue = [True]
    run("dropout", "p3")
    question = answers.questions[0]
    assert "Cleo" in question
    assert not any(name in question for name in NAMES if name != "Cleo")


def test_splice_then_failed_resend(cycle, run, fake_transport):
    fake_transport.refuse = {"bert@example.org"}
    assert run("dropout", "p3", "--yes") == 2
    assert run.out.count("sent") == 1
    assert "spliced; sent 0 of 1" in run.out
    assert "p2: send failed (550)" in run.out
    fake_transport.refuse = set()
    assert run("send") == 0
    assert [m["To"] for m in fake_transport.sent] == ["bert@example.org"]


def test_splice_keeps_replaces_after_failed_send(run, fake_transport):
    run.setup()
    sends = dict(ALL_SENT, p2=SendRecord("failed", "2026-11-21T10:00:00Z", None))
    save_draw(run, CYCLE, sends=sends, replaces={"p2": "2026-11-01T09:00:00Z"})
    assert run("dropout", "p3", "--yes") == 0
    assert run.state().draws[0].replaces["p2"] == "2026-11-01T09:00:00Z"
    assert "vom 01.11.2026 um 10:00" in fake_transport.sent[0].get_content()


def test_splice_with_other_pending(run, fake_transport):
    run.setup()
    sends = {g: r for g, r in ALL_SENT.items() if g != "p4"}
    save_draw(run, CYCLE, sends=sends)
    assert run("dropout", "p3", "--yes") == 0
    assert "spliced; sent 2 of 2" in run.out


def test_failed_resend_keeps_first_date(run, fake_transport):
    run.setup()
    save_draw(run, CYCLE, sends=ALL_SENT)
    fake_transport.refuse = {"bert@example.org"}
    assert run("send", "p2") == 2
    record = run.state().draws[0].sends["p2"]
    assert record.result == "failed" and record.accepted_at == "2026-11-20T19:02:11Z"
    fake_transport.refuse = set()
    assert run("dropout", "p3", "--yes") == 0
    assert "vom 20.11.2026 um 20:02" in fake_transport.sent[0].get_content()


def test_dropout_mutual_pair(run, fake_transport):
    run.setup()
    save_draw(run, {"p1": "p2", "p2": "p1", "p3": "p4", "p4": "p3"}, sends=ALL_SENT)
    assert run("dropout", "p2", "--yes") == 0
    assert "full re-draw; sent 3 of 3" in run.out
    state = run.state()
    assert [d.status for d in state.draws] == ["void", "final"]
    assert len(fake_transport.sent) == 3
    assert all("ersetzt" in m.get_content() for m in fake_transport.sent)


def test_dropout_forbidden_splice(run, fake_transport):
    run.setup()
    older = make_draw({"p2": "p4", "p4": "p3", "p3": "p1", "p1": "p2"}, draw_id="2025-1", year=2025)
    draw = make_draw(CYCLE, sends=ALL_SENT)
    run.save(make_state(older, draw))
    assert run("dropout", "p3", "--yes") == 0
    assert "full re-draw" in run.out
    assert "history: 2025-1" in run.out


def test_full_redraw_next_year(run, year, fake_transport):
    run.setup()
    save_draw(run, {"p1": "p2", "p2": "p1", "p3": "p4", "p4": "p3"}, event_line="Alte Zeile")
    year.value = 2027
    assert run("dropout", "p1", "--yes") == 0
    new = run.state().draws[1]
    assert new.draw_id == "2026-2" and new.year == 2026
    assert new.event_line == "Alte Zeile"
    assert "draw: 2026-2" in run.out


def test_full_redraw_carries_replaces(run, fake_transport):
    run.setup()
    sends = {"p1": accepted(), "p3": SendRecord("failed", "2026-11-22T10:00:00Z", None)}
    replaces = {"p3": "2026-11-01T09:00:00Z", "p4": "2026-11-02T09:00:00Z"}
    save_draw(run, {"p1": "p2", "p2": "p1", "p3": "p4", "p4": "p3"}, sends=sends, replaces=replaces)
    assert run("dropout", "p2", "--yes") == 0
    new = run.state().draws[1]
    assert new.replaces == {
        "p1": "2026-11-20T19:02:11Z",
        "p3": "2026-11-01T09:00:00Z",
        "p4": "2026-11-02T09:00:00Z",
    }


def test_dropout_too_few(run):
    run.setup(2)
    run("draw")
    before = (run.data_dir / "state.enc").read_bytes()
    assert run("dropout", "p1", "--yes") == 1
    assert "fewer than 2" in run.err
    assert (run.data_dir / "state.enc").read_bytes() == before


def test_dropout_unknown(drawn, answers):
    assert drawn("dropout", "p9") == 1
    assert answers.questions == []


def test_dropout_broken_config(drawn):
    before = (drawn.data_dir / "state.enc").read_bytes()
    (drawn.data_dir / "config.toml").unlink()
    assert drawn("dropout", "p1", "--yes") == 1
    assert (drawn.data_dir / "state.enc").read_bytes() == before


@pytest.mark.parametrize("answer", [[False], []])
def test_dropout_declined(drawn, answers, fake_transport, answer):
    answers.queue = answer
    before = (drawn.data_dir / "state.enc").read_bytes()
    assert drawn("dropout", "p1") == 1
    assert "cancelled, nothing changed" in drawn.err
    assert (drawn.data_dir / "state.enc").read_bytes() == before
    assert fake_transport.sent == []


def test_dropout_yes_skips_question(drawn, answers):
    assert drawn("dropout", "p1", "--yes") == 0
    assert answers.questions == []


# --- preflight ----------------------------------------------------------------


def test_preflight_ok(run, fake_transport):
    run.setup()
    assert run("preflight") == 0
    for check in ("participants", "config", "state", "smtp", "draw"):
        assert f"{check}: OK" in run.out
    assert "history: none" in run.out
    assert "relaxation: none" in run.out
    assert fake_transport.logins == 1 and fake_transport.closes == 1
    assert fake_transport.sent == []


def test_preflight_broken_config(run):
    run.setup()
    (run.data_dir / "config.toml").write_text("[smtp\nhost = 1\n")
    assert run("preflight", "--test-email") == 1
    assert "config: FAILED (config.toml: invalid TOML at line" in run.out
    assert "smtp: skipped (needs config)" in run.out
    assert "test-email: skipped (needs config, smtp)" in run.out
    assert "draw: OK" in run.out
    assert "preflight: 1 checks failed" in run.err


def test_preflight_no_smtp_password(run, fake_keychain):
    run.setup()
    del fake_keychain.items["smtp"]
    assert run("preflight") == 1
    assert "smtp: FAILED (Keychain item smtp missing; restore it with" in run.out


def test_preflight_login_failure(run, fake_transport):
    run.setup()
    fake_transport.fail_login("auth", 535)
    assert run("preflight") == 1
    assert "smtp: FAILED (auth failed (535))" in run.out


def test_preflight_no_key(run, fake_keychain):
    run.setup()
    del fake_keychain.items["fernet-key"]
    assert run("preflight") == 1
    assert "state: FAILED" in run.out
    assert "draw: skipped (needs state)" in run.out


def test_preflight_test_email(run, fake_transport):
    run.setup()
    fake_transport.refuse = {"cleo@example.org"}
    assert run("preflight", "--test-email") == 1
    assert "p1: accepted" in run.out
    assert "p3: send failed (550)" in run.out
    assert "test-email: FAILED (1 of 4 failed)" in run.out
    for msg in fake_transport.sent:
        body = msg.get_content()
        others = [n for n in NAMES if n not in body.split(",")[0]]
        assert sum(n in body for n in others) == 0


def test_preflight_test_email_ok(run, fake_transport):
    run.setup()
    assert run("preflight", "--test-email") == 0
    assert len(fake_transport.sent) == 4
    assert "test-email: OK" in run.out


def test_preflight_relaxation(run, year):
    run.setup(3)
    run("draw")
    year.value = 2027
    run("draw")
    year.value = 2028
    assert run("preflight") == 0
    assert "history: 2027-1, 2026-1" in run.out
    assert "relaxation: older_draw" in run.out


# --- status and others ----------------------------------------------------------


def test_status(drawn):
    state = drawn.state()
    state.draws[0].sends["p2"] = SendRecord("failed", "2026-11-21T10:00:00Z", None)
    del state.draws[0].sends["p3"]
    drawn.save(state)
    assert drawn("status") == 0
    assert drawn.out.splitlines() == [
        "draw: 2026-1",
        "relaxation: none",
        "p1: accepted",
        "p2: failed",
        "p3: pending",
        "p4: accepted",
    ]


def test_not_in_draw(drawn):
    text = (drawn.data_dir / "participants.toml").read_text()
    text += '[[participant]]\nid = "p9"\nname = "Ines"\nemail = "ines@example.org"\n'
    (drawn.data_dir / "participants.toml").write_text(text)
    assert drawn("status") == 0
    assert "not in draw: p9" in drawn.out
    assert drawn("preflight") == 0
    assert "not in draw: p9" in drawn.out


def test_status_bad_participants_file(drawn):
    (drawn.data_dir / "participants.toml").write_text("x")
    assert drawn("status") == 0
    assert "warning: participants.toml unreadable" in drawn.err


@pytest.mark.parametrize("command", [["send"], ["dropout", "p1"], ["status"]])
def test_no_final_draw(run, command):
    run.setup()
    assert run(*command) == 1
    assert "no final draw found" in run.err


@pytest.mark.parametrize("argv", [[], ["bogus"], ["draw", "--nope"], ["dropout"]])
def test_usage_errors(run, argv):
    assert run(*argv) == 1
    assert "usage error" in run.err


def test_internal_error(run, monkeypatch):
    run.setup()

    def boom(*args, **kwargs):
        raise RuntimeError("Alma")

    monkeypatch.setattr(solver, "build_draw", boom)
    assert run("draw") == 1
    assert run.err == "internal error: RuntimeError\n"
    assert run.out.count("Alma") == 0


def test_keyboard_interrupt(run, monkeypatch):
    def interrupt(args):
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "cmd_status", interrupt)
    assert run("status") == 1
    assert "cancelled" in run.err


def test_history_over_time(run, year):
    run.setup(6)
    for y in (2026, 2027, 2028):
        year.value = y
        assert run("draw") == 0
    draws = run.state().draws
    assert all(d.relaxed == "none" for d in draws)
    for i, draw in enumerate(draws):
        for earlier in draws[max(0, i - 2) : i]:
            assert not set(draw.pairs.items()) & set(earlier.pairs.items())


# --- confirm ------------------------------------------------------------------


class FakeStdin:
    def __init__(self, text, tty=True, error=None):
        self.text, self.tty, self.error = text, tty, error

    def isatty(self):
        return self.tty

    def readline(self):
        if self.error:
            raise self.error
        return self.text


@pytest.mark.parametrize(
    "stdin,expected",
    [
        (FakeStdin("y\n"), True),
        (FakeStdin("Y\n"), True),
        (FakeStdin("yes\n"), False),
        (FakeStdin("\n"), False),
        (FakeStdin("y\n", tty=False), False),
        (FakeStdin("", error=EOFError()), False),
        (FakeStdin("", error=OSError()), False),
    ],
)
def test_confirm(monkeypatch, capsys, stdin, expected):
    import sys

    monkeypatch.setattr(sys, "stdin", stdin)
    assert real_confirm("Go? [y/N]") is expected
    captured = capsys.readouterr()
    assert captured.out == ""
    if stdin.tty:
        assert captured.err == "Go? [y/N] "


def test_main_module():
    import subprocess
    import sys

    proc = subprocess.run(
        [sys.executable, "-m", "wichteln", "--version"], capture_output=True, text=True
    )
    assert proc.returncode == 0
    assert proc.stdout.startswith("wichteln ")


# --- import -------------------------------------------------------------------


def write_import(run, text):
    path = run.data_dir.parent / "draw-2025.toml"
    path.write_text(text)
    return str(path)


# p1..p4 attend this year; p5 and p6 attended 2025 only.
IMPORT_2025 = """
year = 2025

[pairs]
p1 = "p2"
p2 = "p5"
p5 = "p3"
p3 = "p4"
p4 = "p6"
p6 = "p1"
"""


def test_import_then_draw(run, rng, fake_transport):
    run.setup()
    path = write_import(run, IMPORT_2025)
    assert run("import", path) == 0
    assert "imported: 2025-1 (6 participants)" in run.out
    assert "history: 2025-1" in run.out
    assert "now delete" in run.err and "draw-2025.toml" in run.err
    imported = run.state().draws[0]
    assert imported.imported and imported.status == "final"
    for seed in range(20):
        rng["seed"] = seed
        state = run.state()
        state.draws = state.draws[:1]
        run.save(state)
        assert run("draw") == 0
        assert "history: 2025-1" in run.out
        new = run.state().draws[1]
        assert new.relaxed == "none"
        assert new.pairs["p1"] != "p2" and new.pairs["p3"] != "p4"


def test_import_two_years(run, year):
    run.setup()
    assert run("import", write_import(run, IMPORT_2025)) == 0
    text = '\nyear = 2024\n[pairs]\np1 = "p3"\np3 = "p1"\n'
    assert run("import", write_import(run, text)) == 0
    assert "history: 2025-1, 2024-1" in run.out


def test_send_and_dropout_refuse_imported(run, fake_transport):
    run.setup()
    run("import", write_import(run, IMPORT_2025))
    assert run("send") == 1
    assert "imported" in run.err and "wichteln draw" in run.err
    assert run("send", "p1") == 1
    assert run("dropout", "p1", "--yes") == 1
    assert fake_transport.sent == []
    assert run("status") == 0
    assert run.out.splitlines() == [
        "draw: 2025-1",
        "imported: history only, 6 participants",
    ]


def test_import_refuses_current_year_and_duplicates(run):
    run.setup()
    assert run("import", write_import(run, IMPORT_2025.replace("2025", "2026"))) == 1
    assert "before 2026" in run.err
    assert run("import", write_import(run, IMPORT_2025)) == 0
    assert run("import", write_import(run, IMPORT_2025)) == 1
    assert "a final draw for 2025 exists" in run.err
    assert len(run.state().draws) == 1


def test_import_needs_state(run):
    run.write_participants()
    assert run("import", write_import(run, IMPORT_2025)) == 3


@pytest.mark.parametrize(
    "text,match",
    [
        ('year = 2025\n[pairs]\np1 = "p2"\np2 = "p2"\n', "p2: gives to themselves"),
        ('year = 2025\n[pairs]\np1 = "p2"\np2 = "p3"\np3 = "p2"\n', "p1: never a recipient"),
        ('year = 2025\n[pairs]\np1 = "p2"\np2 = "p1"\n[x]\n', "exactly 'year'"),
        ('year = 2025\n[pairs]\np1 = "p2"\np2 = "p3"\n', "p3: recipient but not a giver"),
        ('year = 2025\n[pairs]\np1 = "p2"\n', "p2: recipient but not a giver"),
        ('year = 2025\n[pairs]\np1 = "p1"\n', "gives to themselves"),
        ('year = 2025\n[pairs]\np1 = "p2"\np2 = "p1"\np3 = "p1"\n', "p3: never a recipient"),
        ('year = 2025\n[pairs]\np1 = "p2"\n[pairs2]\n', "exactly 'year'"),
        ('year = "2025"\n[pairs]\np1 = "p2"\np2 = "p1"\n', "'year' must be an integer"),
        ("year = 2025\npairs = 5\n", "'pairs' must be a table"),
        ('year = 2025\n[pairs]\nAlma = "p2"\np2 = "p1"\n', "a giver ID"),
        ('year = 2025\n[pairs]\np1 = "Bert"\np2 = "p1"\n', "p1: recipient must be"),
        ('year = 2025\n[pairs]\np1 = "p2"\np1 = "p3"\n', "invalid TOML at line 4"),
        ("year = 2025\n[pairs]\n", "at least 2 givers"),
    ],
)
def test_import_invalid(run, text, match):
    run.setup()
    assert run("import", write_import(run, text)) == 1
    assert match in run.err
    assert run.state().draws == []


def test_import_missing_file(run):
    run.setup()
    assert run("import", str(run.data_dir / "nope.toml")) == 1
    assert "nope.toml: not found" in run.err
