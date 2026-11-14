"""Building the plain-text emails. No I/O."""

from __future__ import annotations

from datetime import datetime
from email.message import EmailMessage
from email.utils import formatdate, make_msgid, parseaddr

from wichteln.model import Draw, MailConfig, Participant

SUBJECT = "Dein Wichtel-Los {year}"
TEST_SUBJECT = "Wichteln {year}: Test-E-Mail"
GREETING = "Hallo {name},"
MATCH_LINE = "du beschenkst dieses Jahr: {recipient}."
REPLACES_LINE = "Dieses Los ersetzt die E-Mail vom {date} um {time}."
DRAW_LINE = "Ziehung {draw_id}"
REPLY_LINE = (
    "Bitte nicht auf diese E-Mail antworten. Fragen bitte direkt an den Organisator, "
    "ohne diese E-Mail weiterzuleiten oder zu zitieren."
)
TEST_LINE = (
    "dies ist eine Test-E-Mail für das Wichteln {year}. Sie enthält noch kein Los. "
    "Bitte bestätige im Familienchat, dass sie angekommen ist, und füge den Absender "
    "zu deinen Kontakten hinzu."
)


def _base_message(mail_cfg: MailConfig, to_addr: str, subject: str) -> EmailMessage:
    domain = parseaddr(mail_cfg.from_addr)[1].rpartition("@")[2]
    msg = EmailMessage()
    msg["From"] = mail_cfg.from_addr
    msg["Reply-To"] = mail_cfg.reply_to
    msg["To"] = to_addr
    msg["Subject"] = subject
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=domain)
    msg["Auto-Submitted"] = "auto-generated"
    msg["X-Auto-Response-Suppress"] = "All"
    return msg


def body_lines(giver: Participant, recipient: Participant, draw: Draw) -> list[str]:
    lines = [GREETING.format(name=giver.name), "", MATCH_LINE.format(recipient=recipient.name)]
    if draw.event_line:
        lines.append(draw.event_line)
    if giver.id in draw.replaces:
        t = datetime.fromisoformat(draw.replaces[giver.id]).astimezone()
        lines.append(REPLACES_LINE.format(date=t.strftime("%d.%m.%Y"), time=t.strftime("%H:%M")))
    lines += ["", DRAW_LINE.format(draw_id=draw.draw_id), "", REPLY_LINE]
    return lines


def build_message(
    mail_cfg: MailConfig, giver: Participant, recipient: Participant, draw: Draw, to_addr: str
) -> EmailMessage:
    msg = _base_message(mail_cfg, to_addr, SUBJECT.format(year=draw.year))
    msg.set_content("\n".join(body_lines(giver, recipient, draw)) + "\n", cte="quoted-printable")
    return msg


def build_test_message(mail_cfg: MailConfig, participant: Participant, year: int) -> EmailMessage:
    msg = _base_message(mail_cfg, participant.email, TEST_SUBJECT.format(year=year))
    lines = [
        GREETING.format(name=participant.name),
        "",
        TEST_LINE.format(year=year),
        "",
        REPLY_LINE,
    ]
    msg.set_content("\n".join(lines) + "\n", cte="quoted-printable")
    return msg
