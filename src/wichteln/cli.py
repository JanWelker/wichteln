"""Command-line interface.

Output never pairs a giver with a recipient. The only participant name ever
written is the dropout's own name in the ``dropout`` question.
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime
import secrets
import shutil
import sys
from importlib.resources import files
from pathlib import Path

from cryptography.fernet import Fernet

from wichteln import (
    __version__,
    config,
    keychain,
    mailer,
    model,
    rules,
    solver,
    splice,
    store,
    templates,
)
from wichteln.errors import ConfigError, SendFailures, StateError, UsageError, WichtelnError
from wichteln.model import Draw, MailConfig, SendRecord, SmtpConfig, State

# --- Seams replaced by tests --------------------------------------------------


def make_transport(smtp_cfg: SmtpConfig, password: str, envelope_from: str) -> mailer.Transport:
    return mailer.SmtpTransport(smtp_cfg, password, envelope_from)


def make_rng():
    return secrets.SystemRandom()


def current_year() -> int:
    return datetime.date.today().year


def confirm(question: str) -> bool:
    if not sys.stdin.isatty():
        return False
    sys.stderr.write(question + " ")
    sys.stderr.flush()
    try:
        answer = sys.stdin.readline()
    except (EOFError, OSError):
        return False
    return answer.strip() in ("y", "Y")


# --- Output helpers -----------------------------------------------------------


def out(line: str) -> None:
    print(line)


def err(line: str) -> None:
    print(line, file=sys.stderr)


def history_line(state: State, year: int) -> str:
    ids = [d.draw_id for d in state.history_before(year)[:2]]
    return f"history: {', '.join(ids) if ids else 'none'}"


# --- Loading ------------------------------------------------------------------


def _data_dir() -> Path:
    return config.data_dir()


def _fernet_key_or_none() -> str | None:
    try:
        return keychain.get_secret(keychain.FERNET_ACCOUNT)
    except keychain.SecretMissing:
        return None


def load_context(allow_missing_state: bool = False) -> tuple[bytes, State]:
    data = _data_dir()
    if store.exists(data):
        # A missing key raises SecretMissing with the restore instruction.
        key = keychain.get_secret(keychain.FERNET_ACCOUNT).encode("ascii")
        return key, store.load(data, key)
    key_str = _fernet_key_or_none()
    if key_str is None:
        raise StateError("no Fernet key and no state.enc; run: wichteln init")
    key = key_str.encode("ascii")
    if allow_missing_state:
        return key, State()
    return key, store.load(data, key)  # raises the "state.enc missing" error


def _load_config() -> tuple[SmtpConfig, MailConfig]:
    return config.load_config(_data_dir() / config.CONFIG_FILE)


def _load_participants() -> list[model.Participant]:
    return config.load_participants(_data_dir() / config.PARTICIPANTS_FILE)


def _find_draw(state: State) -> Draw:
    draw = state.latest_final()
    if draw is None:
        raise UsageError("no final draw found; run wichteln draw first")
    return draw


def _file_participants(warning_suffix: str) -> list[model.Participant] | None:
    try:
        return _load_participants()
    except ConfigError as exc:
        err(f"warning: participants.toml unreadable ({exc}){warning_suffix}")
        return None


def _not_in_draw(file_people: list[model.Participant] | None, draw: Draw | None) -> None:
    if file_people is None or draw is None:
        return
    missing = sorted(p.id for p in file_people if p.id not in draw.participants)
    if missing:
        out(f"not in draw: {', '.join(missing)}")


def resolve_addresses(draw: Draw, giver_ids: list[str]) -> tuple[dict[str, str], dict[str, str]]:
    """Return the To address per giver and the confirmed new addresses."""
    file_people = _file_participants("; using addresses from the draw")
    from_file = {p.id: p.email for p in file_people or []}
    to_addrs: dict[str, str] = {}
    new_addrs: dict[str, str] = {}
    for gid in giver_ids:
        old = draw.participants[gid].email
        new = from_file.get(gid)
        if new is None or new == old:
            to_addrs[gid] = old
            continue
        if confirm(f"{gid}: address changed from {old} to {new}. Send to the new address? [y/N]"):
            to_addrs[gid] = new
            new_addrs[gid] = new
        else:
            to_addrs[gid] = old
            err(f"{gid}: using the address stored in the draw")
    return to_addrs, new_addrs


# --- Sending ------------------------------------------------------------------


def send_to(
    key: bytes,
    state: State,
    draw: Draw,
    giver_ids: list[str],
    to_addrs: dict[str, str],
    new_addrs: dict[str, str],
    smtp_cfg: SmtpConfig,
    mail_cfg: MailConfig,
    password: str,
    prefix: str = "",
) -> None:
    data = _data_dir()
    messages = {
        gid: templates.build_message(
            mail_cfg,
            draw.participants[gid],
            draw.participants[draw.pairs[gid]],
            draw,
            to_addr=to_addrs[gid],
        )
        for gid in giver_ids
    }

    def on_result(gid: str, error: mailer.TransportError | None) -> None:
        now = model.now_utc()
        if error is None:
            draw.sends[gid] = SendRecord(result="accepted", at=now, accepted_at=now)
            if gid in new_addrs:
                draw.participants[gid] = dataclasses.replace(
                    draw.participants[gid], email=new_addrs[gid]
                )
        else:
            previous = draw.sends.get(gid)
            draw.sends[gid] = SendRecord(
                result="failed",
                at=now,
                accepted_at=previous.accepted_at if previous else None,
            )
        store.save(data, key, state)

    transport = make_transport(smtp_cfg, password, mail_cfg.envelope_from)
    results = mailer.send_all(transport, messages, on_result)
    failed = {gid: e for gid, e in sorted(results.items()) if e is not None}
    total = len(results)
    out(f"{prefix}sent {total - len(failed)} of {total}")
    for gid, error in failed.items():
        out(f"{gid}: {error.describe()}")
    if failed:
        raise SendFailures(f"{len(failed)} of {total} emails failed")


# --- Commands -----------------------------------------------------------------


def cmd_init(args: argparse.Namespace) -> int:
    data = _data_dir()
    data.mkdir(parents=True, exist_ok=True)
    examples = files("wichteln") / "examples"
    for name in (config.PARTICIPANTS_FILE, config.CONFIG_FILE):
        target = data / name
        if not target.exists():
            with (examples / name).open("rb") as src, open(target, "xb") as dst:
                shutil.copyfileobj(src, dst)
            out(f"created {name}")

    if store.exists(data) or _fernet_key_or_none() is not None:
        load_context()  # raises if only one of them exists, or if they don't match
        out("nothing to do: key and state.enc exist")
        return 0

    key = Fernet.generate_key().decode("ascii")
    keychain.store_fernet_key(key)
    out("Fernet key (store it in your password manager now):")
    out("")
    out(f"    {key}")
    out("")
    out("Then clear the terminal scrollback (Cmd-K).")
    store.save(data, key.encode("ascii"), State())
    out("created state.enc")
    out("next: add the SMTP password with: security add-generic-password -s wichteln -a smtp -U -w")
    return 0


def cmd_preflight(args: argparse.Namespace) -> int:
    failed: list[str] = []
    ok: set[str] = set()

    def report(check: str, error: str | None) -> None:
        if error is None:
            ok.add(check)
            out(f"{check}: OK")
        else:
            failed.append(check)
            out(f"{check}: FAILED ({error})")

    def skip(check: str, needs: list[str]) -> bool:
        missing = [n for n in needs if n not in ok]
        if missing:
            out(f"{check}: skipped (needs {', '.join(missing)})")
            return True
        return False

    people: list[model.Participant] = []
    try:
        people = _load_participants()
        report("participants", None)
    except ConfigError as exc:
        report("participants", str(exc))

    smtp_cfg = mail_cfg = None
    try:
        smtp_cfg, mail_cfg = _load_config()
        report("config", None)
    except ConfigError as exc:
        report("config", str(exc))

    state: State | None = None
    try:
        _, state = load_context()
        report("state", None)
    except StateError as exc:
        report("state", str(exc))

    password = ""
    if not skip("smtp", ["config"]):
        try:
            password = keychain.get_secret(keychain.SMTP_ACCOUNT)
        except StateError as exc:
            report("smtp", str(exc))
        else:
            transport = make_transport(smtp_cfg, password, mail_cfg.envelope_from)
            try:
                transport.login()
            except mailer.TransportError as exc:
                report("smtp", exc.describe())
            else:
                report("smtp", None)
            finally:
                transport.close()

    if not skip("draw", ["participants", "state"]):
        year = current_year()
        _, level = solver.solve_with_relaxation(
            sorted(p.id for p in people), state.history_before(year), make_rng()
        )
        out(history_line(state, year))
        out(f"relaxation: {level}")
        report("draw", None)

    if args.test_email and not skip("test-email", ["participants", "config", "smtp"]):
        year = current_year()
        messages = {p.id: templates.build_test_message(mail_cfg, p, year) for p in people}

        def on_result(gid: str, error: mailer.TransportError | None) -> None:
            out(f"{gid}: accepted" if error is None else f"{gid}: {error.describe()}")

        transport = make_transport(smtp_cfg, password, mail_cfg.envelope_from)
        results = mailer.send_all(transport, messages, on_result)
        bad = sum(1 for e in results.values() if e is not None)
        report("test-email", f"{bad} of {len(results)} failed" if bad else None)

    if state is not None and "participants" in ok:
        _not_in_draw(people, state.latest_final())

    if failed:
        raise UsageError(f"preflight: {len(failed)} checks failed")
    return 0


def cmd_draw(args: argparse.Namespace) -> int:
    smtp_cfg, mail_cfg = _load_config()
    key, state = load_context(allow_missing_state=args.no_history)
    password = keychain.get_secret(keychain.SMTP_ACCOUNT)
    year = current_year()

    voided: Draw | None = None
    existing = state.current(year)
    if existing is not None:
        if not args.redraw:
            raise UsageError(
                f"a draw for {year} exists; use wichteln send to finish sending "
                "or --redraw to replace it"
            )
        question = f"Replace draw {existing.draw_id} and email everyone again? [y/N]"
        if not args.yes and not confirm(question):
            raise UsageError("cancelled, nothing changed")
        voided = existing

    people = {p.id: p for p in _load_participants()}
    if voided is not None:
        voided.status = "void"
    draw = solver.build_draw(
        state, year, people, voided, mail_cfg.event_line, make_rng(), model.now_utc()
    )
    out(history_line(state, year))
    out(f"relaxation: {draw.relaxed}")
    out(f"draw: {draw.draw_id}")
    state.draws.append(draw)
    store.save(_data_dir(), key, state)

    givers = sorted(draw.participants)
    to_addrs = {gid: draw.participants[gid].email for gid in givers}
    send_to(key, state, draw, givers, to_addrs, {}, smtp_cfg, mail_cfg, password)
    return 0


def cmd_send(args: argparse.Namespace) -> int:
    smtp_cfg, mail_cfg = _load_config()
    key, state = load_context()
    draw = _find_draw(state)
    out(f"draw: {draw.draw_id}")
    if args.id is None:
        givers = draw.pending()
        if not givers:
            out("nothing to send")
            return 0
    else:
        if args.id not in draw.participants:
            raise UsageError(f"unknown participant {args.id}")
        givers = [args.id]
    to_addrs, new_addrs = resolve_addresses(draw, givers)
    password = keychain.get_secret(keychain.SMTP_ACCOUNT)
    send_to(key, state, draw, givers, to_addrs, new_addrs, smtp_cfg, mail_cfg, password)
    return 0


def cmd_dropout(args: argparse.Namespace) -> int:
    smtp_cfg, mail_cfg = _load_config()
    key, state = load_context()
    draw = _find_draw(state)
    out(f"draw: {draw.draw_id}")
    dropout = args.id
    if dropout not in draw.participants:
        raise UsageError(f"unknown participant {dropout}")
    if len(draw.participants) - 1 < solver.MIN_PARTICIPANTS:
        raise UsageError("fewer than 2 participants would remain")
    name = draw.participants[dropout].name
    if not args.yes and not confirm(f"Remove {name} ({dropout}) from draw {draw.draw_id}? [y/N]"):
        raise UsageError("cancelled, nothing changed")
    password = keychain.get_secret(keychain.SMTP_ACCOUNT)

    forbidden = rules.forbidden_pairs(state.history_before(draw.year), draw.relaxed)
    new_pairs = splice.splice_out(draw.pairs, dropout, forbidden)
    if new_pairs is not None:
        giver = next(g for g, r in draw.pairs.items() if r == dropout)
        draw.pairs = new_pairs
        for mapping in (draw.participants, draw.sends, draw.replaces):
            mapping.pop(dropout, None)
        record = draw.sends.pop(giver, None)
        if record is not None and record.accepted_at:
            draw.replaces[giver] = record.accepted_at
        target, prefix = draw, "spliced; "
    else:
        draw.status = "void"
        snapshot = {pid: p for pid, p in draw.participants.items() if pid != dropout}
        target = solver.build_draw(
            state,
            draw.year,
            snapshot,
            voided=draw,
            event_line=draw.event_line,
            rng=make_rng(),
            now=model.now_utc(),
        )
        out(history_line(state, draw.year))
        out(f"relaxation: {target.relaxed}")
        out(f"draw: {target.draw_id}")
        state.draws.append(target)
        prefix = "full re-draw; "
    store.save(_data_dir(), key, state)

    givers = target.pending()
    to_addrs, new_addrs = resolve_addresses(target, givers)
    send_to(key, state, target, givers, to_addrs, new_addrs, smtp_cfg, mail_cfg, password, prefix)
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    _, state = load_context()
    draw = _find_draw(state)
    out(f"draw: {draw.draw_id}")
    out(f"relaxation: {draw.relaxed}")
    for gid in sorted(draw.participants):
        record = draw.sends.get(gid)
        out(f"{gid}: {record.result if record else 'pending'}")
    _not_in_draw(_file_participants(""), draw)
    return 0


# --- Parser and entry point -----------------------------------------------------


class Parser(argparse.ArgumentParser):
    def error(self, message: str):
        raise UsageError(f"usage error: {message}")


def build_parser() -> Parser:
    parser = Parser(prog="wichteln", description="Family Secret Santa draw.")
    parser.add_argument("--version", action="version", version=f"wichteln {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("init", help="create the data folder, key and empty state")
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("preflight", help="check everything without sending matches")
    p.add_argument("--test-email", action="store_true", help="send a test email to everyone")
    p.set_defaults(func=cmd_preflight)

    p = sub.add_parser("draw", help="make this year's draw and email everyone")
    p.add_argument("--redraw", action="store_true", help="replace this year's draw")
    p.add_argument("--no-history", action="store_true", help="start without state.enc")
    p.add_argument("--yes", action="store_true", help="answer the --redraw question with yes")
    p.set_defaults(func=cmd_draw)

    p = sub.add_parser("send", help="send pending emails, or one participant's email again")
    p.add_argument("id", nargs="?", help="participant ID")
    p.set_defaults(func=cmd_send)

    p = sub.add_parser("dropout", help="remove a participant from the current draw")
    p.add_argument("id", help="participant ID")
    p.add_argument("--yes", action="store_true", help="answer the question with yes")
    p.set_defaults(func=cmd_dropout)

    p = sub.add_parser("status", help="show send results of the current draw")
    p.set_defaults(func=cmd_status)
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        args = build_parser().parse_args(argv)
        return args.func(args)
    except WichtelnError as exc:
        err(str(exc))
        return exc.exit_code
    except KeyboardInterrupt:
        err("cancelled")
        return 1
    except Exception as exc:
        err(f"internal error: {type(exc).__name__}")
        return 1
