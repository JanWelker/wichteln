"""Sending emails through the SMTP relay.

Errors keep only the step, the SMTP code and the exception class name, never an
address or a server message.
"""

from __future__ import annotations

import smtplib
import ssl
from collections.abc import Callable
from email.message import EmailMessage
from typing import Literal, Protocol

from wichteln.model import SmtpConfig

Step = Literal["connect", "auth", "send"]
TIMEOUT = 30


class TransportError(Exception):
    def __init__(self, step: Step, code: int | None = None, kind: str = ""):
        super().__init__(step, code, kind)
        self.step = step
        self.code = code
        self.kind = kind

    def describe(self) -> str:
        return f"{self.step} failed ({self.code if self.code is not None else self.kind})"


class Transport(Protocol):
    def login(self) -> None: ...

    def send(self, msg: EmailMessage) -> None: ...

    def close(self) -> None: ...


class SmtpTransport:
    def __init__(self, smtp_cfg: SmtpConfig, password: str, envelope_from: str):
        self._cfg = smtp_cfg
        self._password = password
        self._envelope_from = envelope_from
        self._conn: smtplib.SMTP | None = None

    def login(self) -> None:
        cfg = self._cfg
        try:
            if cfg.port == 465:
                conn = smtplib.SMTP_SSL(
                    cfg.host, cfg.port, context=ssl.create_default_context(), timeout=TIMEOUT
                )
                self._conn = conn
            else:
                conn = smtplib.SMTP(cfg.host, cfg.port, timeout=TIMEOUT)
                self._conn = conn
                conn.starttls(context=ssl.create_default_context())
            conn.login(cfg.username, self._password)
        except smtplib.SMTPAuthenticationError as exc:
            raise TransportError("auth", exc.smtp_code, type(exc).__name__) from None
        except (smtplib.SMTPException, OSError) as exc:
            raise TransportError("connect", None, type(exc).__name__) from None

    def send(self, msg: EmailMessage) -> None:
        if self._conn is None:
            raise TransportError("connect", None, "NotConnected")
        try:
            self._conn.send_message(msg, from_addr=self._envelope_from)
        except smtplib.SMTPServerDisconnected as exc:
            raise TransportError("connect", None, type(exc).__name__) from None
        except smtplib.SMTPRecipientsRefused as exc:
            codes = [code for code, _ in exc.recipients.values()]
            code = codes[0] if len(codes) == 1 else None
            raise TransportError("send", code, type(exc).__name__) from None
        except smtplib.SMTPResponseException as exc:
            raise TransportError("send", exc.smtp_code, type(exc).__name__) from None
        except smtplib.SMTPException as exc:
            raise TransportError("send", None, type(exc).__name__) from None
        except OSError as exc:
            raise TransportError("connect", None, type(exc).__name__) from None

    def close(self) -> None:
        conn, self._conn = self._conn, None
        if conn is None:
            return
        try:
            conn.quit()
        except Exception:
            try:
                conn.close()
            except Exception:
                pass


def send_all(
    transport: Transport,
    messages: dict[str, EmailMessage],
    on_result: Callable[[str, TransportError | None], None],
) -> dict[str, TransportError | None]:
    results: dict[str, TransportError | None] = {}
    order = sorted(messages)
    try:
        try:
            transport.login()
        except TransportError as exc:
            for gid in order:
                results[gid] = exc
                on_result(gid, exc)
            return results
        fatal: TransportError | None = None
        for gid in order:
            error = fatal
            if error is None:
                try:
                    transport.send(messages[gid])
                except TransportError as exc:
                    error = exc
                    if exc.step == "connect":
                        fatal = exc
            results[gid] = error
            on_result(gid, error)
        return results
    finally:
        transport.close()
