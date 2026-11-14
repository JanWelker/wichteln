import smtplib
from email.message import EmailMessage

import pytest

from wichteln import mailer
from wichteln.mailer import SmtpTransport, TransportError, send_all
from wichteln.model import SmtpConfig


class FakeSMTP:
    instances = []
    script = {}

    def __init__(self, host, port, context=None, timeout=None):
        self.host, self.port, self.context, self.timeout = host, port, context, timeout
        self.calls = []
        self.sent = []
        FakeSMTP.instances.append(self)
        self._raise("init")

    def _raise(self, name):
        exc = FakeSMTP.script.get(name)
        if exc is not None:
            raise exc

    def starttls(self, context=None):
        self.calls.append("starttls")
        self._raise("starttls")

    def login(self, user, password):
        self.calls.append("login")
        self._raise("login")

    def send_message(self, msg, from_addr=None):
        self.calls.append(("send", msg["To"], from_addr))
        exc = FakeSMTP.script.get(("send", msg["To"]))
        if exc is not None:
            raise exc
        self.sent.append(msg)

    def quit(self):
        self.calls.append("quit")
        self._raise("quit")

    def close(self):
        self.calls.append("close")

    def set_debuglevel(self, level):  # pragma: no cover
        raise AssertionError("debug output enabled")


@pytest.fixture(autouse=True)
def fake_smtp(monkeypatch):
    FakeSMTP.instances = []
    FakeSMTP.script = {}
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(smtplib, "SMTP_SSL", FakeSMTP)
    return FakeSMTP


def transport(port=465):
    return SmtpTransport(SmtpConfig("smtp.example.org", port, "user"), "pw", "bounce@example.org")


def msg(to):
    m = EmailMessage()
    m["To"] = to
    m.set_content("x")
    return m


def messages(*ids):
    return {i: msg(f"{i}@example.org") for i in ids}


def run(t, msgs):
    seen = []
    results = send_all(t, msgs, lambda gid, err: seen.append((gid, err)))
    return results, seen


def test_port_465_uses_ssl(fake_smtp):
    t = transport(465)
    t.login()
    conn = fake_smtp.instances[0]
    assert conn.context is not None and conn.timeout == 30
    assert conn.calls == ["login"]


def test_port_587_uses_starttls(fake_smtp):
    t = transport(587)
    t.login()
    assert fake_smtp.instances[0].calls == ["starttls", "login"]


def test_starttls_failure(fake_smtp):
    fake_smtp.script["starttls"] = smtplib.SMTPNotSupportedError("no tls")
    results, _ = run(transport(587), messages("p1"))
    assert results["p1"].step == "connect"
    assert fake_smtp.instances[0].sent == []
    assert "login" not in fake_smtp.instances[0].calls


def test_auth_failure(fake_smtp):
    fake_smtp.script["login"] = smtplib.SMTPAuthenticationError(535, b"bad")
    results, seen = run(transport(), messages("p1", "p2"))
    assert len(fake_smtp.instances) == 1
    assert all(e.step == "auth" and e.code == 535 for e in results.values())
    assert [g for g, _ in seen] == ["p1", "p2"]
    assert "close" in fake_smtp.instances[0].calls or "quit" in fake_smtp.instances[0].calls


@pytest.mark.parametrize(
    "exc", [smtplib.SMTPNotSupportedError("x"), smtplib.SMTPException("No suitable auth")]
)
def test_other_login_errors(fake_smtp, exc):
    fake_smtp.script["login"] = exc
    with pytest.raises(TransportError) as info:
        transport().login()
    assert info.value.step == "connect"


def test_connect_timeout(fake_smtp):
    fake_smtp.script["init"] = TimeoutError()
    results, _ = run(transport(), messages("p1", "p2", "p3"))
    assert len(fake_smtp.instances) == 1
    assert all(e.step == "connect" and e.kind == "TimeoutError" for e in results.values())


def test_refused_recipient(fake_smtp):
    fake_smtp.script[("send", "p2@example.org")] = smtplib.SMTPRecipientsRefused(
        {"p2@example.org": (550, b"no such user p2@example.org")}
    )
    results, _ = run(transport(), messages("p1", "p2", "p3"))
    assert results["p1"] is None and results["p3"] is None
    err = results["p2"]
    assert err.step == "send" and err.code == 550
    assert "example.org" not in repr(err.args) and "no such user" not in str(err)
    assert len(fake_smtp.instances[0].sent) == 2


@pytest.mark.parametrize("exc", [smtplib.SMTPServerDisconnected("gone"), TimeoutError()])
def test_lost_connection(fake_smtp, exc):
    fake_smtp.script[("send", "p2@example.org")] = exc
    results, seen = run(transport(), messages("p1", "p2", "p3"))
    assert results["p1"] is None
    assert results["p2"].step == "connect" and results["p3"].step == "connect"
    sends = [c for c in fake_smtp.instances[0].calls if isinstance(c, tuple)]
    assert [c[1] for c in sends] == ["p1@example.org", "p2@example.org"]
    assert [g for g, _ in seen] == ["p1", "p2", "p3"]


def test_other_send_errors(fake_smtp):
    fake_smtp.script[("send", "p1@example.org")] = smtplib.SMTPDataError(554, b"spam")
    fake_smtp.script[("send", "p2@example.org")] = smtplib.SMTPException("odd")
    results, _ = run(transport(), messages("p1", "p2", "p3"))
    assert (results["p1"].step, results["p1"].code) == ("send", 554)
    assert (results["p2"].step, results["p2"].code) == ("send", None)
    assert results["p3"] is None


def test_order_and_envelope(fake_smtp):
    run(transport(), messages("p3", "p1", "p2"))
    sends = [c for c in fake_smtp.instances[0].calls if isinstance(c, tuple)]
    assert [c[1] for c in sends] == ["p1@example.org", "p2@example.org", "p3@example.org"]
    assert {c[2] for c in sends} == {"bounce@example.org"}


def test_close_after_send(fake_smtp):
    run(transport(), messages("p1"))
    assert fake_smtp.instances[0].calls[-1] == "quit"


def test_quit_error_swallowed(fake_smtp):
    fake_smtp.script["quit"] = smtplib.SMTPServerDisconnected("x")
    run(transport(), messages("p1"))
    assert fake_smtp.instances[0].calls[-2:] == ["quit", "close"]


def test_close_without_connection():
    transport().close()


def test_send_without_login():
    with pytest.raises(TransportError) as info:
        transport().send(msg("p1@example.org"))
    assert info.value.step == "connect"


def test_describe():
    assert TransportError("send", 550, "X").describe() == "send failed (550)"
    assert TransportError("connect", None, "OSError").describe() == "connect failed (OSError)"


def test_send_all_with_fake_transport(fake_transport):
    fake_transport.disconnect_after = 1
    results, _ = run(fake_transport, messages("p1", "p2", "p3"))
    assert results["p1"] is None
    assert results["p2"].step == "connect" and results["p3"].step == "connect"
    assert fake_transport.closes == 1
    fake_transport.fail_login("auth", 535)
    results, _ = run(fake_transport, messages("p1"))
    assert results["p1"].step == "auth"
    assert fake_transport.closes == 2


def test_no_debuglevel_in_source():
    import inspect

    assert "set_debuglevel" not in inspect.getsource(mailer)
