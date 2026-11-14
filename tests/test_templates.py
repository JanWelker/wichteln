from tests.conftest import make_draw, participants
from wichteln.model import MailConfig
from wichteln.templates import build_message, build_test_message

MAIL = MailConfig(
    from_addr="Wichteln <wichteln@example.org>",
    reply_to="wichteln@example.org",
    envelope_from="bounce@example.org",
    event_line="config line",
)
PAIRS = {"p1": "p2", "p2": "p3", "p3": "p1"}


def message(draw, to_addr="alma@example.org"):
    snap = draw.participants
    return build_message(MAIL, snap["p1"], snap[draw.pairs["p1"]], draw, to_addr)


def test_headers():
    msg = message(make_draw(PAIRS))
    assert msg.get_all("To") == ["alma@example.org"]
    assert msg["Cc"] is None and msg["Bcc"] is None
    assert msg["Reply-To"] == "wichteln@example.org"
    assert msg["From"] == "Wichteln <wichteln@example.org>"
    assert msg["Auto-Submitted"] == "auto-generated"
    assert msg["X-Auto-Response-Suppress"] == "All"
    assert msg["Message-ID"].endswith("@example.org>")
    assert msg["Subject"] == "Dein Wichtel-Los 2026"
    assert msg["Date"]
    assert msg["Content-Transfer-Encoding"] == "quoted-printable"
    for name in ("Alma", "Bert", "Cleo"):
        assert name not in msg["Subject"]


def test_body():
    msg = message(make_draw(PAIRS, event_line="Bescherung am 24.12."), to_addr="new@example.org")
    assert msg.get_content() == (
        "Hallo Alma,\n"
        "\n"
        "du beschenkst dieses Jahr: Bert.\n"
        "Bescherung am 24.12.\n"
        "\n"
        "Ziehung 2026-1\n"
        "\n"
        "Bitte nicht auf diese E-Mail antworten. Fragen bitte direkt an den Organisator, "
        "ohne diese E-Mail weiterzuleiten oder zu zitieren.\n"
    )


def test_empty_event_line():
    body = message(make_draw(PAIRS, event_line="")).get_content()
    assert "\n\n\n" not in body
    assert "config line" not in body
    assert body.startswith("Hallo Alma,\n\ndu beschenkst dieses Jahr: Bert.\n\nZiehung 2026-1\n")


def test_umlauts_are_7bit():
    people = participants(3)
    draw = make_draw(PAIRS, event_line="Bescherung bei Müllers")
    msg = build_message(MAIL, people["p1"], people["p2"], draw, "alma@example.org")
    assert msg.as_bytes().isascii()
    assert "Müllers" in msg.get_content()


def test_replacement_body():
    assert "ersetzt" not in message(make_draw(PAIRS)).get_content()
    draw = make_draw(PAIRS, replaces={"p1": "2026-11-20T19:02:11Z"})
    body = message(draw).get_content()
    assert "Dieses Los ersetzt die E-Mail vom 20.11.2026 um 20:02." in body
    other = draw.participants
    body2 = build_message(MAIL, other["p2"], other["p3"], draw, "b@example.org").get_content()
    assert "ersetzt" not in body2


def test_test_message():
    people = participants(3)
    msg = build_test_message(MAIL, people["p1"], 2026)
    body = msg.get_content()
    assert msg["Subject"] == "Wichteln 2026: Test-E-Mail"
    assert msg["To"] == "alma@example.org"
    assert body.count("Hallo Alma,") == 1
    assert "Test-E-Mail für das Wichteln 2026" in body
    assert "Bitte nicht auf diese E-Mail antworten." in body
    assert "Bert" not in body and "Cleo" not in body
    assert msg["Auto-Submitted"] == "auto-generated"
