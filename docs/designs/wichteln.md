# Wichteln: Self-Hosted Family Secret Santa Draw

*   **Author:** Jan Welker
*   **Status:** Proposed
*   **Date:** 2026-11-12

--------------------------------------------------------------------------------

## Overview

Wichteln is a small self-hosted tool that runs the family's yearly Secret Santa draw. The admin keeps a list of participants (name and email address) and runs the draw once. The tool picks a valid draw and emails each person only the name of the person they give a gift to. The admin is also a participant and doesn't see anyone else's match by accident. The tool runs only when the admin calls it and exits afterwards. It has no web interface, no logins and no service that runs between draws.

The tool uses the two previous final draws as history so that matches don't repeat. It stores every draw encrypted, so the admin can't read them at a glance. When someone drops out after the draw, the tool reconnects the chain around them when the rules allow it, so only one match changes. Otherwise it makes a full new draw.

### Terms

*   **Match:** the person a giver gives a gift to (giver → recipient).
*   **Draw:** the full set of matches for one year. A draw is either **final** (the current one) or **void** (replaced by a later draw and never counted as history).
*   **History:** the two most recent final draws from earlier years. Their matches may not repeat.
*   **Snapshot:** the names and email addresses stored inside a draw when it is made. It decides who takes part in that draw.
*   **Pending:** a giver whose email for the current draw hasn't been accepted by the relay yet (no send result, or a failed one).
*   **Replacement body:** the email text used when a giver's match changed after they already received an email. It names the earlier email by date and time.
*   **Splice:** reconnecting the chain around a dropout. If G gives to the dropout D and D gives to R, G now gives to R.
*   **Relaxation level:** which history rules a draw had to drop to find a valid draw (see [Draw rules and the solver](#draw-rules-and-the-solver)).

## The Problem

The family (2 to 10 adults, aged 30 to 60; the brief said fewer than 10, and the limit was raised to 10 on purpose) draws names on paper once a year. This fails in four ways:

1.  **People draw themselves.** The draw then has to be repeated on the spot.
2.  **People who aren't there can't draw.** Someone has to draw for them and pass the name on, so at least one other person knows the match.
3.  **People forget who they drew.** By December they ask the person who organised the draw, who then has to find out and becomes the one person who knows the match.
4.  **The same matches come up again.** People don't want to give a gift to the same person they gave to in either of the two previous years. Paper can't enforce that.

The first three problems end with the organiser handling matches by hand, which is what the family wants to stop. The fourth needs a record of earlier draws, which paper doesn't keep.

Free hosted services such as Drawnames and Elfster solve these problems, but they keep the full participant list, every match and any history on a third-party server. The family wants to avoid that for privacy reasons, so the tool must run on hardware the admin controls. Email delivery still passes each participant's own match through the SMTP relay and the participant's own mail provider. The design's guarantee is narrower: no third party *stores* the participant list, the history or the state. The SMTP relay passes each match email through, as any mail provider does, and may keep copies or logs; that is an accepted risk (see [Risks and Mitigations](#risks-and-mitigations)).

The proposed solution is a command-line tool. The admin edits a participant file, runs a check, and then runs the draw. Each person gets one email with their match. If someone loses the email, the admin runs `wichteln send <id>` for that person. It sends the existing match again, and the admin doesn't see it.

Success means that, after one season, the admin has not had to look up or pass on any match by hand. If participants don't read or trust the emails, the family returns to paper. That is the failure case this design has to avoid.

## Goals

*   **G1: One command makes the draw and delivers it.** A single `draw` command reads the participant list, picks a valid draw and emails each participant only their own match.
*   **G2: No self-matches.** No participant is ever assigned to themselves.
*   **G3: No recent repeats.** A directed match (A gives to B) that appeared in either of the two previous final draws is not used again. B giving to A is still allowed. History starts empty: no paper draws are imported.
*   **G4: The tool always ends.** If no draw meets all rules, the tool first drops the rule for the older of the two previous draws, then the rule for the newer one, and tells the admin which rule it relaxed. It never loops forever and never shows matches while doing this.
*   **G5: The admin doesn't see matches by accident.** No match appears in the tool's terminal output, in log files, in git, or in readable form in stored files. Given a relay account used only for Wichteln whose mailbox, including its Sent folder, replies and bounces, the admin doesn't read routinely and empties unread after each gift exchange, no match reaches the admin's normal inbox through Sent copies, bounces or replies. Auto-replies are discouraged by headers, not prevented.
*   **G6: Dropouts change one match when the rules allow it.** When a participant drops out after the draw, the tool splices them out, so only the dropout's giver gets a new match and an email. If the splice breaks a rule, the tool makes a full new draw and emails everyone in it. Every email states which draw it belongs to, and a replacement email names the earlier email it replaces by date and time.
*   **G7: Lost emails can be recovered without the admin seeing them.** `wichteln send <id>` sends a participant their current match again, with the same text as before. It never starts a new draw.
*   **G8: Problems show up before draw day.** `wichteln preflight` checks the participant file, the SMTP login, the state and key, and whether a valid draw exists, without sending any matches. With `--test-email` it sends every participant a test email that contains no match.
*   **G9: No accidental second draw.** Once a final draw exists for a year, `draw` refuses to run again unless the admin passes `--redraw`, and points to `wichteln send`. If sending fails part-way, `wichteln send` sends only the missing emails, from the same stored draw.
*   **G10: Lost history is detected.** If the key is missing, the tool refuses to run until the key is restored from the password manager. If the key is lost for good, the admin moves `state.enc` aside and runs `init`. If `state.enc` is missing but the key exists, `draw` refuses unless the admin passes `--no-history`. `preflight` and `draw` print the IDs of the draws used as history, so a stale restore can be seen.
*   **G11: Only yearly upkeep.** The only upkeep is running `preflight` before the draw, reinstalling the tool if the Python environment broke, and emptying the Wichteln mailbox after the gift exchange.

## Non-Goals

*   **Logins, accounts, invitations or accept steps.** The admin enters email addresses and everyone listed takes part.
*   **Wish lists, budgets, gift tracking or messages between participants.** The email may contain a fixed free-text line (for example a budget or the date of the gift exchange), but the tool doesn't manage these.
*   **A web interface or anything participants can reach.** Participants only receive email. There is no self-service resend.
*   **More than one group or more than 10 participants.** The solver's memoised search has 2ⁿ states and is specified for n ≤ 10.
*   **Partner or household exclusions.** The only rules are no self-matches and no recent repeats.
*   **Protection against an admin who looks on purpose.** Anyone holding the Fernet key and `state.enc` can decrypt every match. The same holds for any program run as the admin's macOS user, which can read the key with `security find-generic-password`. The design only prevents accidental viewing.
*   **Hiding dropouts from other participants.** A participant who gets a "your match changed" email can guess that someone dropped out. After a splice, the dropout's giver receives the dropout's former recipient, so if they know who dropped out, they learn that person's match. With 10 or fewer people this can't be avoided without emailing everyone.
*   **Hiding from the admin who gave to a dropout.** After a splice, only the dropout's giver is pending. If that giver's replacement email fails, or their address in `participants.toml` changed, the failure line, the address question or `status` shows that giver's ID. Because the admin knows who dropped out, they then learn that match. Hiding pending givers would remove the only way to fix a bad address, so this is accepted.
*   **Late joiners.** A participant joining after the draw means `draw --redraw`, and everyone gets a replacement email. Inserting a late joiner into one match is listed under [Future Improvements](#future-improvements).
*   **Telling people removed before a re-draw.** Givers who are in a voided draw but not in the new one (removed from `participants.toml` before a `--redraw`) get no email. The admin tells them.
*   **Importing past paper draws.** History starts with the first draw made by the tool.
*   **Deleting old draws.** All draws stay in `state.enc`. Pruning would gain little, because the laptop backup keeps older versions of the file anyway, and void draws are needed to number new draws.
*   **A database server, metrics or alerting.** One draw holds at most 10 matches and 10 send records.

## Critical User Journeys (CUJs)

### CUJ 1: Yearly draw

*   **Given:** the admin has a participant file with names, fixed IDs and email addresses, the SMTP account is configured in `config.toml`, its password is in the Keychain (see [Backup and recovery](#backup-and-recovery)), and history holds up to two earlier final draws.
*   **When:** the admin runs `preflight --test-email`, confirms in the family chat that everyone received the test email, then runs `draw`.
*   **Then:** each participant receives one email naming only their own recipient, with the draw ID. The admin's terminal shows the history draw IDs, the relaxation level and "sent N of N", and no recipient names. The draw is stored encrypted as the final draw for the year.

### CUJ 2: No valid draw under all rules

*   **Given:** a group of 3, where the two previous final draws leave no valid draw.
*   **When:** the admin runs `preflight` or `draw`.
*   **Then:** the tool reports that it relaxed the rule for the older draw (or both draws) and doesn't name any match. `draw` continues with the relaxed rules. The result still has no self-matches.

### CUJ 3: Someone forgets their match

*   **Given:** a final draw exists and participant P has deleted their email.
*   **When:** P asks the admin, and the admin runs `wichteln send P`.
*   **Then:** P receives the same email text again. The admin sees only "sent 1 of 1". No new draw is made.

### CUJ 4: Someone drops out after the draw

*   **Given:** a final draw exists. D drops out. G gives to D and D gives to R.
*   **When:** the admin runs `wichteln dropout D` and confirms the question.
*   **Then:** if G giving to R breaks no rule, only G receives an email that says it replaces the email from `<date>` at `<time>`, and the stored draw is updated. Otherwise the tool voids the draw and makes a full new draw for the same year. Every participant who received an email from the voided draw gets a replacement email, and the voided draw is not counted in history. D gets no email; the admin tells D directly.

### CUJ 5: A mistyped email address

*   **Given:** one address in the participant file is mistyped, and the Wichteln mailbox was emptied unread after the last gift exchange.
*   **When:** the admin runs `preflight --test-email`, before any draw exists.
*   **Then:** the test email bounces. The mailbox holds only test bounces, which contain no match, so the admin can read them, fix the address and run `preflight` again. Late bounces of real emails are covered in [Risks and Mitigations](#risks-and-mitigations).

## Technical Plan (Architecture)

### Decisions taken by the author

*   **Runs on the admin's laptop** as a command-line program. There is no cluster component, image, service or hostname.
*   **Stored draws are encrypted** with Fernet (the `cryptography` Python package). The key lives in the macOS Keychain and has a second copy in the admin's password manager. `init` stores the key in the Keychain itself and checks it by reading it back.
*   **Mutual pairs are allowed.** A and B may draw each other in the same year. As a result, a splice fails when the dropout and their giver drew each other, and the tool then makes a full new draw.
*   **Any group of 2 to 10 is accepted,** with no warning for small groups. With 2 or 3 people everyone can work out the matches, and the design accepts that.
*   **The dropout gets no email.** The admin tells them directly.
*   **History means the two previous final draws** from earlier years, not calendar years. A skipped year doesn't drop history.
*   **A fixed address is not a dropout.** The admin corrects `participants.toml` and runs `wichteln send <id>`.
*   **The stored draw decides who takes part.** `participants.toml` is the input for new draws. It does not change who is in an existing draw.
*   **Address changes after the draw need confirmation.** If a giver's address in `participants.toml` differs from the one stored in the draw, the tool shows the giver ID and both addresses and asks before sending to the new one. This stops a swapped or mistyped address from sending a match to the wrong person.
*   **The splice is checked only at the draw's stored relaxation level.** If G→R is forbidden at that level, the tool makes a full new draw, even if that draw later relaxes the same rule. The splice therefore never relaxes a rule the original draw kept. This is deliberate: a splice that relaxes rules would need its own search over levels.

### Components

```text
                    admin's laptop
 ┌──────────────────────────────────────────────────────────────┐
 │  wichteln CLI (Python)                                       │
 │                                                              │
 │   cli ──► solver ──► store ──► templates ──► mailer ─────────┼──► SMTP relay ──► participant inboxes
 │    │   (pure, no I/O) (Fernet file)            ▲             │        │
 │    │                     ▲                     │             │        └─ late bounces, replies ──► dedicated
 │    ▼                     │                     │             │                                     Wichteln mailbox
 │   terminal: counts,      │                     │             │                                     (not the admin's
 │   IDs, levels only       │                     │             │                                      normal inbox)
 │                          │                     │             │
 │   macOS Keychain ◄──► keychain ──► Fernet key ─┘             │
 │                          └──────► SMTP password ──► mailer   │
 │                                                              │
 │   data folder (~/Wichteln, covered by the laptop backup):    │
 │     participants.toml   plain text, no matches  ──► config   │
 │     config.toml         plain text, no secrets  ──► config   │
 │     state.enc           encrypted: all draws and send results│
 └──────────────────────────────────────────────────────────────┘
```

The program has these modules. Only `solver`, `rules` and `splice` contain the draw logic.

1.  **`cli`** reads arguments, calls the other modules, asks the `[y/N]` questions and prints results. Output never pairs a giver with a recipient.
2.  **`model`** holds the data types and the conversion of the state to and from JSON.
3.  **`config`** loads and checks `participants.toml` and `config.toml`.
4.  **`solver`, `rules` and `splice`** are pure functions with no file, network or clock access. Given participant IDs, a set of forbidden directed matches and a random-number source, the solver returns a uniformly random valid draw, or nothing when none exists. It always terminates.
5.  **`store`** reads and writes `state.enc`. It writes atomically, so a crash of the tool leaves either the old or the new file.
6.  **`templates`** builds one plain-text email per participant.
7.  **`mailer`** sends the emails through the SMTP relay. The result of each send is recorded in the state.
8.  **`keychain`** reads the Fernet key and the SMTP password from the macOS Keychain, and writes only the Fernet key, by calling the built-in `security` command. This avoids an extra Python package for Keychain access.
9.  **`errors`** defines the tool's exception classes and their exit codes.

### Data files

All files live in one data folder, `~/Wichteln` by default. The `WICHTELN_HOME` environment variable can change it. Tests use a temporary folder through the same variable, so a test never touches real history. The data folder is not a git repository. The admin checks that it is covered by the laptop's normal backup (for example Time Machine).

**`participants.toml`** (plain text, edited by hand):

```toml
[[participant]]
id = "jan"            # fixed, never reused; history refers to this
name = "Jan"
email = "jan@example.org"
```

The `id` stays the same across years even if the name or email changes. Removing a participant from this file doesn't delete their history or remove them from the current draw.

**`config.toml`** (plain text, no secrets):

```toml
[smtp]
host = "smtp.example.org"
port = 465                       # 465 = TLS from the start; 587 = STARTTLS
username = "wichteln@example.org"

[mail]
from = "Wichteln <wichteln@example.org>"
reply_to = "wichteln@example.org"               # dedicated mailbox, not the admin's normal inbox
envelope_from = "wichteln@example.org"          # receives late bounces
event_line = "Bescherung am 24.12. bei ..."     # optional free text
```

The subject is fixed in the code, so it can never contain a name.

**`state.enc`** (Fernet-encrypted JSON). Decrypted, it looks like this:

```json
{
  "format": 1,
  "draws": [
    {
      "draw_id": "2026-1",
      "year": 2026,
      "status": "final",
      "relaxed": "none",
      "created_at": "2026-11-20T19:02:05Z",
      "participants": {
        "jan": {"name": "Jan", "email": "jan@example.org"},
        "anna": {"name": "Anna", "email": "anna@example.org"}
      },
      "pairs": {"jan": "anna", "anna": "jan"},
      "event_line": "Bescherung am 24.12. bei ...",
      "replaces": {},
      "sends": {
        "jan": {"result": "accepted", "at": "2026-11-20T19:02:11Z", "accepted_at": "2026-11-20T19:02:11Z"},
        "anna": {"result": "failed", "at": "2026-11-20T19:02:12Z", "accepted_at": null}
      }
    }
  ]
}
```

| Field | Meaning |
|---|---|
| `format` | Version of the file layout. Only `1` exists. |
| `draw_id` | `<year>-<k>`, where k counts the draws (final and void) made for that year, starting at 1. Shown in every email and in the history lines. |
| `year` | The year the draw is for. |
| `status` | `final` or `void`. A `void` draw is kept for the record but never counts as history. |
| `relaxed` | `none`, `older_draw` or `both_draws`: the relaxation level the draw needed. |
| `created_at` | When the draw was made. |
| `participants` | The snapshot: everyone in the draw at draw time. It decides who takes part. |
| `pairs` | Giver ID → recipient ID. |
| `event_line` | Copy of `mail.event_line` from `config.toml` at draw time, so a resend has the same text even if the config changed. |
| `replaces` | Giver ID → time of the earlier email this giver's next email replaces. Empty for a first draw. |
| `sends` | Giver ID → result of the latest send (`result`, `at`) and `accepted_at`, the time of the last accepted send. A failed send keeps the earlier `accepted_at`, so a giver who once received an email is never treated as if they hadn't. A giver with no entry or a `failed` result is pending. |

Timestamps are ISO-8601 UTC with a `Z` suffix. Fernet detects tampering or a wrong key, and the tool then stops with an error instead of misreading the file.

### Draw rules and the solver

**Forbidden matches.** For a new draw in year Y, the tool takes the two most recent `final` draws from years before Y. Each giver→recipient match in them is forbidden. If fewer than two such draws exist, the missing ones forbid nothing. Self-matches are always forbidden. Matches are directed: A→B forbids only A→B, not B→A.

**Relaxation levels.** The tool tries three levels in order and uses the first one that has a valid draw:

| Level | Forbidden matches |
|---|---|
| `none` | self-matches, matches from both previous final draws |
| `older_draw` | self-matches, matches from the newer previous final draw only |
| `both_draws` | self-matches only |

At `both_draws` a valid draw always exists for 2 or more participants. Every arrangement of people in one cycle (A→B→C→…→A) is valid. The level used is printed and stored, never the matches.

**Search.** The solver counts all valid draws at a level, picks one at random with equal probability, and reports when the count is 0, which proves that no valid draw exists at that level. The [Detailed Implementation Plan](#detailed-implementation-plan) gives the algorithm.

**Group size.** The tool rejects fewer than 2 or more than 10 participants.

### Commands

`draw` and `preflight` work on the current local year. `send`, `dropout` and `status` work on the newest `final` draw of any year and print its ID, so a lost email found on 2 January still works. There is no option to choose a year.

| Command | What it does | What it prints |
|---|---|---|
| `wichteln init` | Creates the data folder, copies the example files if absent, and creates the Fernet key and an empty `state.enc`, but only when neither a key nor a `state.enc` exists. | The key, once, with the instruction to store it in the password manager and clear the terminal scrollback; then the steps done |
| `wichteln preflight [--test-email]` | Runs every check and reports each: participant file (unique IDs and emails, 2 to 10 people), config, key and state present and readable, SMTP password and login, and the relaxation level a draw would need. Lists IDs in the file that aren't in the newest final draw. With `--test-email`, sends every participant an email that contains no match. | OK, an error or "skipped" per check; history draw IDs; relaxation level; test-email results per participant ID. Exit 1 if any check failed |
| `wichteln draw [--redraw] [--no-history] [--yes]` | Refuses if a `final` draw exists for this year (exit 1, pointing to `send`), unless `--redraw` is given, which asks `Replace draw <draw_id> and email everyone again? [y/N]` and then voids that draw. `--yes` skips the question. Solves, stores the draw before sending, then sends. `--no-history` allows a draw when `state.enc` is missing and creates an empty one with the existing key. | History draw IDs, relaxation level, "sent X of N", one line per failed send |
| `wichteln send [<id>]` | Without `<id>`, sends every pending email of the newest final draw. With `<id>`, sends that participant's current email again, whatever its status. Doesn't change the matches. If a giver's address in `participants.toml` differs from the stored one, asks `[y/N]` before using the new one. | "sent X of N", one line per failed send |
| `wichteln dropout <id> [--yes]` | Checks the ID and that at least 2 participants would remain, then asks `Remove <name> (<id>) from draw <draw_id>? [y/N]` (`--yes` skips the question). Then splices the dropout out if the rules allow it. Otherwise voids the draw and makes a full new draw for the same year without them. Then sends only the pending emails. | "spliced; sent X of N" or "full re-draw; sent X of N", where N is the number of pending givers |
| `wichteln status` | Shows the newest final draw's ID, relaxation level, and per giver ID the latest send result. Lists IDs in the file that aren't in that draw. | Giver IDs and send results, never recipients |

`draw` stores the draw before sending any email. If the program stops part-way, `send` finishes the job from the same stored draw, and the guard in `draw` stops a second draw from being made by accident.

### Dropout splice

Given the newest final draw with G→D and D→R:

1.  If D isn't in the draw, stop with exit code 1.
2.  If fewer than 2 participants would remain, stop with exit code 1 and leave the state unchanged.
3.  Ask the confirmation question, unless `--yes` is given. Anything but `y` stops with exit code 1 and changes nothing.
4.  If G = R (G and D drew each other), splicing would make G draw themselves. Go to step 6.
5.  If G→R is forbidden at the draw's stored relaxation level, go to step 6. Otherwise splice:
    1.  Set G→R.
    2.  Remove D from `pairs`, `participants`, `sends` and `replaces`.
    3.  If `sends[G].accepted_at` is set, set `replaces[G]` to it. Otherwise keep any existing `replaces[G]` unchanged.
    4.  Delete `sends[G]`, which makes G pending.
    5.  Save, then send to the pending givers. Done.
6.  Mark the draw `void` and make a full new draw for the same year, from the voided draw's snapshot minus D and with the voided draw's `event_line`. The search starts again at relaxation level `none`. A giver who received an email from the voided draw gets a replacement email naming its date and time. Other givers keep any earlier replacement entry. Givers missing from the new draw get no entry. Save, then send to everyone in the new draw.

The command doesn't edit `participants.toml`, and D can stay in it or be removed.

### Emails

*   Plain text only, in German. One email per participant, addressed only to them. No CC or BCC, and never a copy to the admin.
*   **Subject:** fixed in the code: `Dein Wichtel-Los {year}`. It never contains a name.
*   **Body** (fixed in the code): these lines, joined with line breaks:
    1.  `Hallo {name},`
    2.  an empty line
    3.  `du beschenkst dieses Jahr: {recipient}.`
    4.  `{event_line}`, only if it isn't empty
    5.  `Dieses Los ersetzt die E-Mail vom {date} um {time}.`, only in the replacement body. The date and time are `replaces[giver]` in local time, as `dd.mm.yyyy` and `HH:MM`, so two replacements on the same day can be told apart.
    6.  an empty line
    7.  `Ziehung {draw_id}`
    8.  an empty line
    9.  `Bitte nicht auf diese E-Mail antworten. Fragen bitte direkt an den Organisator, ohne diese E-Mail weiterzuleiten oder zu zitieren.`

    Names come from the draw's snapshot, and the event line from the draw. Only the `To` address may come from the current `participants.toml`.
*   **Which body:** the replacement body is used when `replaces[giver]` exists. Every sending path (`draw`, `send`, `send <id>`, `dropout`) uses this rule, so a resend has the same text as the original.
*   **Headers:**
    *   `From` and `Reply-To` point to the dedicated Wichteln mailbox.
    *   The envelope sender (`Return-Path`) comes from `envelope_from`, so bounces go to the same mailbox.
    *   `Auto-Submitted: auto-generated` and `X-Auto-Response-Suppress: All` discourage auto-replies.
    *   Each email has a unique `Message-ID`.
*   **Connection:** TLS on port 465, or STARTTLS on port 587. The tool never sends without encryption.
*   **Accepted:** "accepted" in the send log means the relay accepted the message. Delivery to the inbox isn't confirmed.
*   **Relay:** any SMTP provider. Host, port, username, sender, reply and bounce addresses are set in `config.toml`. The provider choice doesn't change the code and can be made later.
    *   **G5 condition:** G5 holds only if the account is used only for Wichteln and the admin doesn't routinely read its mailbox, including the Sent folder. A provider that saves Sent copies is acceptable on that condition.
    *   **Spam:** SPF, DKIM and DMARC for the sending domain lower the chance that receiving servers classify the emails as spam. The admin sets them up where the provider allows it.
*   **SMTP password:** the admin stores it once with `security add-generic-password -s wichteln -a smtp -U -w`, which prompts for it. It must be printable ASCII, because `security` prints other passwords as hex. The tool only reads it.

### Keeping matches out of sight

| Place a match could appear | How the design keeps it out of sight |
|---|---|
| Terminal output | Commands print counts, levels, draw IDs and giver IDs. The only name printed is the dropout's own name in the `dropout` question. Only the tool's own exceptions print their message, and those never contain a name. Every other error prints only its class name. |
| Logs | The tool writes no log files and has no debug mode. |
| Sent folder | The relay account is dedicated to Wichteln, and the admin doesn't read its Sent folder. It is emptied unread after each gift exchange. |
| Bounces | The envelope sender points to the dedicated mailbox, which is emptied unread after each gift exchange. The test email before the draw catches bad addresses. |
| Replies and auto-replies | `Reply-To` points to the dedicated mailbox. The body asks people not to reply or quote. The `Auto-Submitted` and `X-Auto-Response-Suppress` headers discourage auto-replies. |
| Data files | `state.enc` is encrypted. The plain-text files contain no matches. |
| Git and backups | No git repository holds participant data. The laptop backup holds `state.enc` encrypted. The key is kept in the Keychain and the password manager; the one-time printout at `init` is cleared from the terminal scrollback. |

### Backup and recovery

*   **What is backed up:** the laptop's normal backup covers the data folder. Only `state.enc` matters for history, and it is encrypted.
*   **Key backup:** at `init`, the tool prints the Fernet key once so the admin can store it in a password manager. To restore it, run `security add-generic-password -s wichteln -a fernet-key -U -w`, which prompts for the key.
*   **Key lost for good:**
    1.  Move the old `state.enc` out of the data folder.
    2.  If a damaged key is still in the Keychain, delete it with `security delete-generic-password -s wichteln -a fernet-key`.
    3.  Run `wichteln init`. With neither a key nor a `state.enc`, it creates a new key and an empty state and prints the key for the password manager.
    4.  Run `wichteln draw`. History is empty, so no earlier matches are excluded.
*   **Missing key or state.** `preflight` reports each of these as a failed check and exits with 1, so it can still show the other checks. Every other command stops with exit code 3:
    *   **Key missing, `state.enc` present:** every command, `init` included, stops and gives the instruction to restore the key.
    *   **Key present, `state.enc` missing:** every command, `init` included, stops. The exception is `draw --no-history`, which starts an empty history.
    *   **Both missing:** every command except `init` stops and points to `wichteln init`. `init` creates both.
    *   **Damaged state or mistyped key:** the command stops with "malformed state" or "invalid key format".

## Alternatives Considered

Each rejection below is the author's decision. The early ones (A, B, I) were made during brainstorming and are recorded in [`concepts_brief.md`](../../concepts_brief.md). The others were made while drafting and in the review interviews, which are recorded in [`goldfish_review_report_round1.md`](../../goldfish_review_report_round1.md), [`goldfish_review_report_round2.md`](../../goldfish_review_report_round2.md), [`goldfish_review_report.md`](../../goldfish_review_report.md) and [`consolidated_review_report.md`](../../consolidated_review_report.md).

### Alternative A: Free hosted service (Drawnames, Elfster and similar)

*   **Pros:** Nothing to build or maintain. Self-exclusion and email delivery are built in. Participants may already know these sites.
*   **Cons:** The full participant list, every match and any history are stored by a third party. History exclusions have to be entered by hand each year, if the service supports them at all.
*   **Reason for Rejection:** One third party would store the whole family's data, every match and the history, which the family wants to avoid.

### Alternative B: Web app with magic-link sign-in

*   **Pros:** Participants could look up their match themselves at any time, so lost emails wouldn't need the admin.
*   **Cons:** A public login page has to stay running all year for one action a year. It needs its own sign-in, plus a hostname, TLS, storage and updates.
*   **Reason for Rejection:** A service running all year, with its own sign-in and updates, for one action a year. Email delivery plus `wichteln send <id>` covers lost emails without one.

### Alternative C: Manually started Job on the homelab cluster (`homelab-apps`)

The admin runs a Kubernetes homelab managed with Argo CD, with OpenBao for secrets (which has to be unlocked by hand after a restart) and Authentik for login.

*   **Pros:** Everything lives in GitOps, Renovate keeps the image updated, and nothing depends on the admin's laptop. Velero backs up the history volume.
*   **Cons:** Upkeep all year (container image, Renovate pull requests, OpenBao secret, Cilium network policy) for one run a year. The draw fails if OpenBao is still locked on draw day. An Argo CD sync can start an extra run. Commands that take arguments (`send <id>`, `dropout <id>`) are awkward as Jobs. Backups stay inside the cluster.
*   **Reason for Rejection:** The upkeep and the failure modes on draw day outweigh the benefit of GitOps for a yearly run. A laptop tool meets the privacy goal with nothing running between draws.

### Alternative D: Existing open-source Secret Santa tool

*   **Pros:** Less code to write.
*   **Cons:** The tools identified without a web search are small SMTP scripts, for example `mveytsman/secret-santa`, that handle self-exclusion and fixed exclusion lists. None was known to handle multi-year history, the no-valid-draw case, dropout splicing, resend, or keeping matches out of output and storage.
*   **Reason for Rejection:** Whatever tool a survey finds, it would hold the SMTP password and handle every match. Before use, its storage, logging and output would need a full audit against G5. It would also have to be extended for the history rules (G3, G4), the dropout splice (G6) and resend (G7). Writing those parts directly avoids running unaudited code with the family's data. This reason doesn't depend on the survey.

### Alternative E: Storing state with `age` or base64 instead of Fernet

*   **Pros:** `age` keeps the Python code free of third-party packages. Base64 needs no key and no dependency at all.
*   **Cons:** `age` is an extra program to install and keep working on the laptop. Base64 only stops a casual glance: a diff tool, backup viewer or assistant reading the folder would decode and show the matches.
*   **Reason for Rejection:** `age` adds an external program that has to be present and working once a year. Base64 gives no protection against tools that decode it. Fernet with the key in the Keychain avoids both at the cost of one Python dependency.

### Alternative F: Storing history as keyed hashes (HMAC) instead of encrypting it

*   **Pros:** The tool can check "was this match used before?" without storing names. The history file is safe to copy anywhere.
*   **Cons:** `send` and `dropout` need the real current matches, so the current draw must be stored in a form the tool can read back anyway. That means two storage schemes in one tool. With at most 90 possible matches, anyone with the key can recover every match from its hash in seconds, so hashing adds no protection over encryption.
*   **Reason for Rejection:** One encrypted state file covers the current draw and history with a single mechanism and no loss of protection.

### Alternative G: Full re-draw on every dropout

*   **Pros:** Simpler code, and the result looks like any other draw.
*   **Cons:** Everyone receives a second email that overrides the first, and people who already bought a gift would have to start again.
*   **Reason for Rejection:** It sends everyone a replacement when one changed match would do. A full re-draw remains the fallback when the splice breaks a rule.

### Alternative H: Shuffle and reject until a valid draw appears

*   **Pros:** A few lines of code. After an existence check, rejecting invalid shuffles gives a uniform result too.
*   **Cons:** Without an existence check it loops forever when no valid draw exists. Its run time is random and unbounded, and it still needs a separate search to decide the relaxation level.
*   **Reason for Rejection:** The count already decides the relaxation level, and counting then picking has a bounded run time.

### Alternative I: Scheduled CI job (GitHub Actions)

*   **Pros:** No laptop needed. Runs on a schedule.
*   **Cons:** The SMTP password, the participant list and the encryption key would sit with a third party. Job logs are stored and readable by the repository owner, which makes accidental exposure more likely.
*   **Reason for Rejection:** Its advantages don't outweigh the third-party exposure of secrets and job logs.

### Alternative J: Paper draw with written rules

*   **Pros:** No technology. Everyone understands it.
*   **Cons:** A self-draw is only fixed by repeating the draw. Absent people and people who forget are not helped.
*   **Reason for Rejection:** It solves only the first of the four problems. It stays the fallback if adoption is low.

### Alternative K: Minimum-change re-solve after a dropout

*   **Pros:** Avoids most full re-draws. A dropout who drew their own giver could be handled by changing 2 or 3 matches instead of N-1.
*   **Cons:** An exactly uniform choice among the draws that change the fewest matches needs inclusion-exclusion over subsets of givers, which is a second solver mode with its own tests. It would also tell more participants that something changed.
*   **Reason for Rejection:** It needs a second solver mode for a fallback that only happens when a dropout drew their own giver or G→R is forbidden. The full re-draw is a correct fallback.

### Alternative L: A delivery channel other than email (messenger bot, sealed envelopes)

*   **Pros:** A messenger bot avoids spam filters and bounces. Sealed envelopes need no third party at all.
*   **Cons:** A bot needs an account per participant, a provider API and a running process. Envelopes need the admin to print and hand out matches, which brings back problem 2 for absent people and makes `send <id>` impossible.
*   **Reason for Rejection:** Everyone in the family already has email, no extra account is needed, and email supports resending through `send <id>`.

## Risks and Mitigations

| Risk | Mitigation |
|---|---|
| The Fernet key is lost | Restore it from the password manager. If that copy is lost too, move `state.enc` aside and run `init`, then `draw`. The next draw then has no history, and the one after it has only one previous draw to exclude. |
| Emails land in spam | SPF, DKIM and DMARC for the sending domain, where the provider allows it. Family-chat confirmation of the test email before `draw`. |
| A match is quoted back to the admin through a reply, bounce or Sent copy | Dedicated Wichteln mailbox and relay account, the reply line in the body, auto-reply headers, the test email before the draw, and emptying the mailbox unread after each gift exchange. |
| A real email bounces after the draw | Mail servers often accept a message and bounce it later, so the tool can't always report it. Such bounces quote the match and stay in the dedicated mailbox unread. The admin learns of the failure when the participant says they got nothing, fixes the address and runs `send <id>`. |
| The Python or uv environment breaks between yearly runs | Run `preflight` a few weeks before the draw. Reinstall with `uv tool install --reinstall --python 3.12 --managed-python .` if needed. |
| A crash after the relay accepted a message but before the state was saved | The state is saved after every message, so at most one email is sent twice, with the same text. Accepted. |
| An unexpected `internal error: <Class>` on draw day | Run `uv run pytest` in the code repository to find the broken part. Tracebacks aren't shown, because they can contain matches. |
| The tool only works on macOS (Keychain, `security`) | Accepted. |
| The SMTP relay keeps copies or logs of match emails | Choose a provider without content retention where possible. Accepted: every mail provider sees the emails it delivers. |
| The laptop is lost or stolen | `state.enc` is encrypted, and the key is protected by the login keychain. Until a replacement Mac is restored from the backup and the key from the password manager (see [Backup and recovery](#backup-and-recovery)), `send` and `dropout` aren't available. |
| Admin types the wrong ID in `dropout`, or runs `--redraw` by mistake | A `[y/N]` question names the dropout or the draw before anything changes. |
| Admin swaps or mistypes an address in `participants.toml` after the draw | The tool asks before sending to an address that differs from the one stored in the draw. |
| Two commands run at the same time | Assumed not to happen: one admin runs the tool by hand. There is no lock. |
| A compromised `cryptography` release | Accepted. It is the only runtime dependency, a widely used package, and it is updated only by the yearly reinstall. |

## Non-Functional Requirements

*   **Security and privacy:**
    *   Matches are stored only in `state.enc`, encrypted with Fernet (AES-128-CBC with an HMAC-SHA256 check).
    *   The key and the SMTP password live in the macOS Keychain, never in files or in git. They are never passed as command-line arguments.
    *   The code repository and the data folder are separate. The code repository's `.gitignore` lists `/participants.toml`, `/config.toml` and `/state.enc` by name, which keeps these files out of `git add` by default.
*   **Performance:** with 10 participants and no history, counting and picking finish in under 2 seconds. A test in the default test run checks this.
*   **Upgrades:** `state.enc` carries `format: 1`. The tool refuses any other format. A migration is written when a second format exists.
*   **Rollback:** `draw --redraw` voids the current draw and sends a new one. People who received an email from the voided draw get the replacement body with that email's date and time. People who didn't receive one keep any earlier replacement line (see [Dropout splice](#dropout-splice) step 6), and otherwise get the normal body. A damaged `state.enc` is restored from the laptop backup.

## Additional Resources

*   [`concepts_brief.md`](../../concepts_brief.md): brainstorm brief and the first independent review.
*   [`consolidated_review_report.md`](../../consolidated_review_report.md): the latest full review and the author's decisions on it. Earlier rounds are in [`implementation_readiness_report_round2.md`](../../implementation_readiness_report_round2.md) and the `goldfish_review_report*.md` files.

## Future Improvements

*   **Calendar reminder:** attach an `.ics` event for the gift exchange with the match in its description, so the calendar reminds people. Not in v1 because attachments from a new sender raise the spam risk.
*   **Self-service resend:** a participant sends an email to a fixed address and gets their match back. Only worth building if `send <id>` requests become frequent.
*   **Late-joiner insertion:** pick a match G→R where G→N and N→R are allowed and make it G→N→R, so only G and the new participant N get an email. Not in v1 because late joiners are a non-goal.

## Open Questions

*   **Mail provider:** not chosen yet, and not needed for the design. It is set in `config.toml` before the first `preflight`.

--------------------------------------------------------------------------------

## Detailed Implementation Plan

The code lives in this repository (`/Users/welker/Dev/wlkr.ch/wichteln`). The admin's data lives in a separate folder, `~/Wichteln` unless `WICHTELN_HOME` says otherwise. Inside the data folder, the tool writes `state.enc` (and briefly `state.enc.tmp` while saving). `init` also writes the two example files and stores the key in the Keychain.

**Toolchain:**
*   **Python:** 3.12, managed by uv and pinned in `.python-version`. uv-managed Python is built to verify TLS certificates without the "Install Certificates" step that the python.org installer for macOS needs. The `preflight` SMTP login checks this; the README gives the fix if it fails.
*   **Tools:** `uv` for the environment and lock file, `pytest` and `pytest-cov` for tests, and `ruff` for linting and formatting.
*   **Runtime dependency:** only `cryptography`, declared as `cryptography>=N`, where N is the major version current at implementation. There is no upper bound, so the yearly reinstall never needs a bound raised.
*   **Install:** `uv tool install --python 3.12 --managed-python .`.

**Exit codes shared across commands:**

| Code | Meaning | Raised by |
|---|---|---|
| 0 | Success | |
| 1 | Input or usage error, or failed `preflight` checks | `UsageError`, `ConfigError`, `KeyboardInterrupt`, any unexpected exception |
| 2 | Some emails failed to send | `SendFailures` |
| 3 | State, key or Keychain error | `StateError` |

The work is split into five phases. Each phase ends with `uv run pytest`, `uv run ruff check .` and `uv run ruff format --check .` passing. The coverage gates in the Verification Plan apply only at the end of Phase 5. Every phase has at least one test, and no file depends on a file from a later phase. Files that grow over several phases are listed again as **Modify** in the phase that extends them.

### Phase 1: Scaffold

#### 1. `pyproject.toml` (Create)

*   **Type / Scope**: Build configuration.
*   **Proposed Changes**:
    *   `[build-system]`: `requires = ["uv_build>=X.Y,<X.(Y+1)"]`, where X.Y is the uv_build version current at implementation, and `build-backend = "uv_build"`.
    *   `[project]`: name `wichteln`, `version = "0.1.0"`, `requires-python = ">=3.12"`, and the dependency `cryptography>=N`.
    *   `[project.scripts]`: `wichteln = "wichteln.cli:main"`.
    *   `[dependency-groups]`: `dev = ["pytest", "pytest-cov", "ruff"]`.
    *   `[tool.ruff]`: `line-length = 100`. `[tool.ruff.lint]`: `select = ["E", "F", "I", "B", "UP"]`.
    *   `[tool.pytest.ini_options]`: `testpaths = ["tests"]` and `markers = ["real_keychain: run keychain.py itself, with only subprocess.run replaced"]`.
    *   `[tool.coverage.run]`: `branch = true`, `source = ["wichteln"]`.
    *   `[tool.uv]`: `required-version = ">=X.Y"`, the first uv version that has both `--managed-python` and the `uv_build` backend.

#### 2. `uv.lock` (Create)

*   **Type / Scope**: Lock file generated by `uv lock`.
*   **Proposed Changes**: Pins the exact versions for the development and test environment. The installed tool uses the newest versions allowed by `pyproject.toml`, because `uv tool install` doesn't read the lock file.

#### 3. `.gitignore` (Create)

*   **Type / Scope**: Repository hygiene.
*   **Proposed Changes**: Ignores `.venv/`, `__pycache__/`, `.pytest_cache/`, `.ruff_cache/`, `.coverage` and `dist/`, and by name `/participants.toml`, `/config.toml` and `/state.enc`. This keeps data files out of `git add` by default. The example files under `src/wichteln/examples/` aren't affected.

#### 4. `.python-version` (Create)

*   **Type / Scope**: Interpreter pin, created with `uv python pin 3.12`.
*   **Proposed Changes**: Contains `3.12`, so `uv sync` and `uv run` use Python 3.12.

#### 5. `src/wichteln/__init__.py` (Create)

*   **Type / Scope**: Package marker.
*   **Proposed Changes**: Defines `__version__ = importlib.metadata.version("wichteln")`.

#### 6. `src/wichteln/__main__.py` (Create)

*   **Type / Scope**: Entry point.
*   **Proposed Changes**: `raise SystemExit(cli.main())`, so that `python -m wichteln` works and returns the exit code.

#### 7. `src/wichteln/errors.py` (Create)

*   **Type / Scope**: Exception classes.
*   **Proposed Changes**: `WichtelnError(Exception)` with a class attribute `exit_code`, and these subclasses:

    | Class | Exit code | Used for |
    |---|---|---|
    | `UsageError` | 1 | bad arguments, unknown IDs, no draw found, declined questions, failed `preflight` checks |
    | `ConfigError` | 1 | unreadable or invalid `participants.toml` or `config.toml` |
    | `SendFailures` | 2 | some emails failed |
    | `StateError` | 3 | missing or unreadable key, missing or damaged `state.enc`, Keychain access failures |

    A message never contains a participant's name. It is built only from participant IDs, draw IDs, file and key names, counts, exit codes, line and column numbers, exception class names and fixed text, so `cli` may print it. The file is created in Phase 1 because `model.py` (Phase 2) already raises `StateError`.

#### 8. `src/wichteln/cli.py` (Create, stub)

*   **Type / Scope**: Command-line entry point, placeholder.
*   **Proposed Changes**: Defines `main(argv: list[str] | None = None) -> int`, which prints `wichteln <__version__>` and returns 0. This keeps the console script and `python -m wichteln` working from Phase 1. The real commands replace it in Phase 5 (item 33). The smoke test doesn't call `main`, because a bare call becomes a usage error in Phase 5; item 35 tests the real behaviour.

#### 9. `tests/test_smoke.py` (Create)

*   **Type / Scope**: Smoke tests.
*   **Proposed Changes**:
    *   `wichteln.__version__` is a non-empty string.
    *   Each class in `errors.py` has the exit code from the table above.

### Phase 2: Draw logic

#### 10. `src/wichteln/model.py` (Create)

*   **Type / Scope**: Data types, no I/O apart from reading the clock in `now_utc`.
*   **Proposed Changes**:
    *   **Constant:** `ID_PATTERN = re.compile(r"[a-z0-9-]{1,32}")`, always used with `ID_PATTERN.fullmatch(...)` so that a trailing newline is rejected. Used by `config.load_participants` and `from_dict`.
    *   **Dataclasses and literals:** `Participant`, `SmtpConfig`, `MailConfig` and `SendRecord` are frozen. `Draw` and `State` are ordinary dataclasses that the commands change in place; changes reach disk only through `store.save`.
        *   `Participant(id: str, name: str, email: str)`
        *   `SmtpConfig(host: str, port: int, username: str)` and `MailConfig(from_addr: str, reply_to: str, envelope_from: str, event_line: str)`
        *   `Relaxation = Literal["none", "older_draw", "both_draws"]` and `LEVELS: tuple[Relaxation, ...] = ("none", "older_draw", "both_draws")`, defined here so that `from_dict` can check `relaxed` without importing `rules.py`
        *   `SendRecord(result: Literal["accepted", "failed"], at: str, accepted_at: str | None)`. A new accepted send sets `accepted_at = at`. A failed send copies `accepted_at` from the giver's previous record, or `None`.
        *   `Draw(draw_id: str, year: int, status: Literal["final", "void"], relaxed: Relaxation, created_at: str, participants: dict[str, Participant], pairs: dict[str, str], event_line: str, replaces: dict[str, str], sends: dict[str, SendRecord])`
        *   `State(format: int, draws: list[Draw])`
    *   **Methods:**
        *   `State.current(year) -> Draw | None` returns the `final` draw for that year.
        *   `State.latest_final() -> Draw | None` returns the `final` draw with the highest `year`.
        *   `State.history_before(year) -> list[Draw]` returns the `final` draws of earlier years, newest first.
        *   `Draw.pending() -> list[str]` returns the giver IDs with no send record or a `failed` one, sorted.
    *   **Timestamps:** `now_utc() -> str` returns `datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")`. It is the only source of stored timestamps.
    *   **Serialisation:**
        *   **Shape:** `to_dict` and `from_dict` convert to and from the JSON shape in the Technical Plan.
        *   **Format first:** `from_dict` checks `format` before anything else. Unless `type(data["format"]) is int` and its value is 1 (so `true` and `"1"` are rejected), it raises `StateError("unsupported state format")`.
        *   **Other checks:** it raises `ValueError`, which `store.load` turns into `StateError("malformed state")`, when:
            *   `status`, `relaxed` or `result` has an unknown value
            *   `year` isn't an int (`type(x) is int`)
            *   a participant ID doesn't match `ID_PATTERN`
            *   a key of `pairs`, `sends` or `replaces` isn't a snapshot ID
            *   in a `final` draw, `pairs` doesn't map every snapshot ID to a different snapshot ID

            Missing keys and wrong value types surface as `KeyError` or `TypeError` while building the objects, and are mapped the same way. Fernet already rejects files the tool didn't write, so these checks guard against the tool's own bugs; the `pairs` check stops a broken state from producing emails.

#### 11. `src/wichteln/rules.py` (Create)

*   **Type / Scope**: Pure functions.
*   **Proposed Changes**:
    *   `from wichteln.model import LEVELS` and `__all__ = ["LEVELS", "forbidden_pairs"]`, so the re-export passes ruff's unused-import check. `model.py` never imports `rules.py`.
    *   `forbidden_pairs(history: list[Draw], level: Relaxation) -> set[tuple[str, str]]` collects the matches from the newer draw (`history[0]`, if it exists) unless the level is `both_draws`, and from the older draw (`history[1]`, if it exists) only when the level is `none`. Self-matches aren't included, because the solver always excludes them.

#### 12. `src/wichteln/solver.py` (Create)

*   **Type / Scope**: Pure functions.
*   **Proposed Changes**:
    *   `count_assignments(ids: list[str], forbidden: set[tuple[str, str]]) -> int`
    *   `nth_assignment(ids, forbidden, n: int) -> dict[str, str]`
    *   `solve(ids, forbidden, rng) -> dict[str, str] | None` returns `None` when the count is 0, otherwise `nth_assignment(..., rng.randrange(count))`. The command passes `secrets.SystemRandom()`; tests pass a seeded `random.Random`.
    *   `solve_with_relaxation(ids, history, rng) -> tuple[dict[str, str], Relaxation]` tries each level in `LEVELS` and returns the first solution. It raises `ValueError` for fewer than 2 or more than 10 IDs. After the loop it has `raise AssertionError("both_draws always has a solution")  # pragma: no cover`, because for 2 or more IDs the loop always returns.
    *   **`build_draw(state: State, year: int, participants: dict[str, Participant], voided: Draw | None, event_line: str, rng, now: str) -> Draw`** builds every new draw. `draw` and the dropout re-draw both use it. The new draw's fields:
        *   **`draw_id`:** `f"{year}-{k}"`, where k is 1 plus the number of draws (final and void) for `year` in `state`.
        *   **`pairs` and `relaxed`:** from `solve_with_relaxation(sorted(participants), state.history_before(year), rng)`, always starting at `none`.
        *   **`participants`:** the given dict, which becomes the snapshot.
        *   **`created_at`:** `now`.
        *   **`event_line`:** the given value. `draw` passes `mail_cfg.event_line`; the dropout re-draw passes the voided draw's `event_line`.
        *   **`sends`:** empty.
        *   **`replaces`:** for each giver g in `participants`, in this order:
            *   if `voided.sends[g].accepted_at` is set, use it
            *   otherwise, if `voided.replaces` has g, carry that value over
            *   otherwise, no entry

            Givers in `voided` who aren't in `participants` get no entry.

    Pseudocode for counting and picking. Both walk the same search tree in the same order, so index `n` always means the same assignment:

    ```text
    allowed[g] = sorted(r for r in ids if r != g and (g, r) not in forbidden)
    order givers by len(allowed[g]) ascending (fewest options first; fixed tie-break by id)

    count(i, used):
        if i == len(givers): return 1
        total = 0
        for r in allowed[givers[i]] if r not in used:
            total += count(i + 1, used | {r})
        return total

    nth(i, used, n, acc):
        if i == len(givers): return acc
        for r in allowed[givers[i]] if r not in used:
            c = count(i + 1, used | {r})
            if n < c: return nth(i + 1, used | {r}, n, acc | {givers[i]: r})
            n -= c
        raise AssertionError("index out of range")  # pragma: no cover
    ```

    `count` is an inner function decorated with `functools.cache`, keyed on `(i, frozenset(used))`. `used` always has `i` elements, so there are at most 2¹⁰ = 1024 states. The fall-through at the end of `nth` can't happen for 0 ≤ n < count, so it is excluded from coverage.

#### 13. `src/wichteln/splice.py` (Create)

*   **Type / Scope**: Pure function.
*   **Proposed Changes**: `splice_out(pairs: dict[str, str], dropout: str, forbidden: set[tuple[str, str]]) -> dict[str, str] | None`.
    1.  `R = pairs[dropout]`, which raises `KeyError` for an unknown dropout. The CLI checks this first (Dropout splice step 1).
    2.  Find G with `pairs[G] == dropout`.
    3.  If `G == R` or `(G, R) in forbidden`, return `None`. Otherwise return a new dict without `dropout` and with `G → R`.

#### 14. `tests/conftest.py` (Create)

*   **Type / Scope**: Test fixtures for Phase 2. Later phases extend this file (items 24, 30 and 34).
*   **Proposed Changes**:
    *   An autouse fixture sets the time zone with `monkeypatch.setenv("TZ", "Europe/Zurich")` and `time.tzset()`, so date and time formatting gives the same result on every machine.
    *   `make_state` builds a `State` directly from `model` types, for tests that need a fixed draw such as a mutual pair. It uses only Phase 2 modules.
    *   Test participant names share no substring with any test ID (for example IDs `p1` to `p9`, names `Alma`, `Bert`, …). A printed ID can then never cause a false failure of the name-leak check in item 35.

#### 15. `tests/test_model.py` (Create)

*   **Type / Scope**: Unit tests.
*   **Proposed Changes**:
    *   **ID pattern:** `ID_PATTERN.fullmatch` accepts `p1`, `a-b` and a 32-character ID. It rejects `P1`, the empty string, `a_b`, `"p1\n"` and a 33-character ID.
    *   **Round trip:** `to_dict`/`from_dict` round-trips a state with void and final draws, `event_line`, `replaces` and `sends`, including a failed record that keeps an earlier `accepted_at`.
    *   **Format check:** `from_dict` raises `StateError("unsupported state format")` for `format: 2`, `format: true` and `format: "1"`.
    *   **Other checks:** `from_dict` raises `ValueError` for `status: "done"`, `relaxed: "x"`, `year: "2026"`, an uppercase participant ID, a `sends` key that isn't in the snapshot, and a final draw whose `pairs` has a self-match.
    *   **`Draw.pending()`:** returns givers with no record or a failed one, sorted.
    *   **`history_before` and `latest_final`:** skip `void` draws; `history_before` also skips draws from the same or later years and returns newest first; `latest_final` returns the final draw with the highest year.
    *   **`now_utc()`:** matches `\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z`.

#### 16. `tests/test_rules.py` (Create)

*   **Type / Scope**: Unit tests.
*   **Proposed Changes**:
    *   **Two draws of history:** `forbidden_pairs` returns the union of both draws for `none`, the newer draw only for `older_draw`, and nothing for `both_draws`.
    *   **One draw of history:** `none` and `older_draw` return `history[0]`'s matches, and `both_draws` returns none.
    *   **No history:** every level returns none.

#### 17. `tests/test_solver.py` (Create)

*   **Type / Scope**: Unit and property tests.
*   **Proposed Changes**:
    *   **Derangement counts:** for n from 2 to 8 with no forbidden matches, `count_assignments` equals the number of derangements: n=2 → 1, n=3 → 2, n=4 → 9, n=5 → 44, n=6 → 265, n=7 → 1854, n=8 → 14833.
    *   **Random cases:** for 1,000 seeds and random forbidden sets, every result has no self-matches and no forbidden matches, and covers each ID exactly once as giver and as recipient.
    *   **Impossible case:** n=3 with both cycles forbidden returns `None`.
    *   **Relaxation:** `solve_with_relaxation` falls back to `older_draw` and then to `both_draws` in prepared examples, and raises for 1 or 11 IDs.
    *   **Uniformity:** with a seeded `random.Random(1)`, n=4 with no history, 9,000 calls to `solve`: each of the 9 possible assignments appears 1,000 ± 150 times.
    *   **Performance:** for 10 participants with no history, `count_assignments` plus one `nth_assignment` call finish in under 2 seconds.
    *   **`build_draw`:**
        *   `draw_id` counts both void and final draws of the year.
        *   `replaces` comes from `accepted_at` in `voided.sends` (also when the latest result is `failed`), carries over `voided.replaces` for givers without one, and has no entry for givers missing from `participants`.
        *   Relaxation starts at `none` even when `voided.relaxed` was `both_draws`.
        *   `event_line` is the value passed in.

#### 18. `tests/test_splice.py` (Create)

*   **Type / Scope**: Unit tests.
*   **Proposed Changes**:
    *   A splice in a 5-cycle succeeds and changes exactly one giver.
    *   A mutual pair (G→D, D→G) returns `None`.
    *   A forbidden G→R returns `None`.
    *   An unknown dropout raises `KeyError`, not `StopIteration`.
    *   The result never contains the dropout as giver or recipient.

### Phase 3: Configuration, Keychain and state

#### 19. `src/wichteln/examples/participants.toml` (Create)

*   **Type / Scope**: Example data, shipped inside the package.
*   **Proposed Changes**: Three made-up participants with IDs `p1` to `p3` and names `Alma`, `Bert` and `Cleo`, so they follow the no-shared-substring rule in item 14. `init` reads it with `importlib.resources.files("wichteln") / "examples" / "participants.toml"` and copies it into the data folder. uv_build includes files inside the module folder in the wheel.

#### 20. `src/wichteln/examples/config.toml` (Create)

*   **Type / Scope**: Example configuration, shipped inside the package.
*   **Proposed Changes**: The `config.toml` from the Technical Plan with example values. `init` copies it the same way.

#### 21. `src/wichteln/config.py` (Create)

*   **Type / Scope**: File loading and validation.
*   **Proposed Changes**:
    *   `data_dir() -> Path` returns `$WICHTELN_HOME` or `~/Wichteln`.
    *   **Reading files:** both loaders read with `with open(path, "rb") as f: data = tomllib.load(f)`. Errors become `ConfigError`, and none of the messages contain text from the file:
        *   **Missing file:** `ConfigError(f"{path.name}: not found")`.
        *   **Broken TOML:** the line and column are taken from the `TOMLDecodeError` message with the pattern `\(at line (\d+), column (\d+)\)`, giving `ConfigError(f"{path.name}: invalid TOML at line {line}, column {column}")`, or `invalid TOML` if the pattern doesn't match. The parser's own message isn't printed, because some messages quote key names, and a key could be a name.
        *   **Not UTF-8:** a `UnicodeDecodeError` becomes `ConfigError(f"{path.name}: not valid UTF-8")`.
        *   **Other read errors:** any other `OSError` (for example a folder or an unreadable file) becomes `ConfigError(f"{path.name}: cannot read ({type(exc).__name__})")`.
    *   **Shape checks:** before reading values, each loader checks the structure, so no `KeyError` or `TypeError` can escape:
        *   `participants.toml`: `participant` must be a list of tables, and each table must have exactly the keys `id`, `name` and `email`, all strings.
        *   `config.toml`: the `smtp` and `mail` tables must exist, every required key must be present, `port` must be an int and every other value a string.
        *   A mismatch raises `ConfigError` naming the file, the participant ID or position where known, and the key.
    *   **Email shape:** an address has exactly one `@`, a non-empty part before it, a dot in the part after it, and no whitespace.
    *   **`load_participants(path) -> list[Participant]`** checks for:
        *   unique IDs
        *   unique emails, compared in lower case
        *   IDs matching `ID_PATTERN.fullmatch`
        *   every email passing the email shape check
        *   2 to 10 entries

        Each problem raises `ConfigError` naming the participant ID and the key name.
    *   **`load_config(path) -> tuple[SmtpConfig, MailConfig]`:**
        *   **Required keys:** `smtp.host`, `smtp.port`, `smtp.username`, `mail.from`, `mail.reply_to` and `mail.envelope_from`. `mail.event_line` is optional.
        *   **Addresses:** the address in `from` (after `email.utils.parseaddr`), `reply_to` and `envelope_from` must pass the email shape check, so the `Message-ID` domain is never empty.
        *   **Port:** must be 465 or 587.

#### 22. `src/wichteln/keychain.py` (Create)

*   **Type / Scope**: macOS Keychain access through `/usr/bin/security`.
*   **Proposed Changes**:
    *   **Command path:** `SECURITY = "/usr/bin/security"`. Every call uses this absolute path in an argument list (no shell) and `subprocess.run(..., capture_output=True, text=True)`, so the `security>` prompt and any output never reach the terminal.
    *   **Account names:** `FERNET_ACCOUNT = "fernet-key"` and `SMTP_ACCOUNT = "smtp"`, both under the service name `wichteln`.
    *   **`get_secret(account: str) -> str`:** runs `[SECURITY, "find-generic-password", "-s", "wichteln", "-a", account, "-w"]`.
        *   **Exit 0:** returns stdout without its trailing newline. It doesn't try to decode hex: `security -w` prints a password that isn't printable ASCII as hex, and a printable ASCII password can look like hex too. Such an SMTP password shows up as an `auth` failure in `preflight`, and the README requires printable ASCII.
        *   **Exit 44 (item not found):** raises `StateError(f"Keychain item {account} missing; restore it with: security add-generic-password -s wichteln -a {account} -U -w")`.
        *   **Any other exit (locked keychain, denied access, no GUI session):** raises `StateError(f"keychain access failed (exit {code})")`. It doesn't show the restore hint, because the item may exist.
    *   **`store_fernet_key(key: str) -> None`:** the only write function. It stores only Fernet keys; the SMTP password is added by the admin with the prompting `security` command from the README, never by the tool.
        1.  Check that `re.fullmatch(r"[A-Za-z0-9_-]{43}=", key)` matches (44 characters of URL-safe base64, the format of `Fernet.generate_key()`). Otherwise raise `ValueError`. Because these characters need no quoting, the line in step 2 can't be split into extra words by `security -i`.
        2.  Run `[SECURITY, "-i"]` with `input=f"add-generic-password -s wichteln -a fernet-key -U -w {key}\n"`. The key goes through standard input, never into the process's arguments.
        3.  Ignore the exit status of `security -i`, because it doesn't reliably show whether the inner command succeeded. Instead read the key back with `get_secret(FERNET_ACCOUNT)`.
        4.  If the read-back raises, or returns a different value, raise `StateError("storing the key in the Keychain failed")`.
    *   **Calls through the module:** only `cli` calls these, as `keychain.get_secret(...)` and `keychain.store_fernet_key(...)`, so tests can replace them. `store` receives the key as a parameter.
    *   **Key types:** the Keychain holds the key as `str`. `init` stores `Fernet.generate_key().decode("ascii")`, and `load_context` returns `keychain.get_secret(FERNET_ACCOUNT).encode("ascii")`.
    *   **No printing:** secret values are never printed by this module.

#### 23. `src/wichteln/store.py` (Create)

*   **Type / Scope**: Encrypted state file.
*   **Proposed Changes**:
    *   **`load(dir, key: bytes) -> State`:**
        *   **Missing file:** raises `StateError("state.enc missing; restore it from the backup or run: wichteln draw --no-history")` if `state.enc` doesn't exist.
        *   **Bad key:** a `ValueError` from `Fernet(key)` (a key that isn't 32 bytes of URL-safe base64, for example a typo during recovery) becomes `StateError("invalid key format")`. `cryptography` already turns base64 errors into `ValueError`.
        *   **Can't decrypt:** `InvalidToken` becomes `StateError("cannot decrypt: wrong key or damaged file")`.
        *   **Bad content:** `json.JSONDecodeError`, `UnicodeDecodeError`, and `KeyError`, `TypeError` or `ValueError` from `from_dict` all become `StateError("malformed state")`. A `StateError` from the format check passes through unchanged. The original exception isn't included, so no field values are printed.
    *   **`save(dir, key, state)`:**
        1.  Serialise to compact JSON and encrypt.
        2.  Remove any existing `state.enc.tmp`, then create it with `os.open(path, O_WRONLY | O_CREAT | O_EXCL, 0o600)`. Wrap the descriptor with `os.fdopen(fd, "wb")`, write, `flush()`, then `os.fsync(f.fileno())`.
        3.  `os.replace` it onto `state.enc`.

        A crash of the tool at any point leaves either the old or the new `state.enc`. A power loss in the second the save takes is covered by the laptop backup.
    *   `exists(dir) -> bool`.

#### 24. `tests/conftest.py` (Modify)

*   **Type / Scope**: Test fixtures for Phase 3.
*   **Proposed Changes**:
    *   `data_dir` (autouse) sets `WICHTELN_HOME` to a pytest `tmp_path`, so no test can touch the real data folder.
    *   `fake_keychain` (autouse) replaces `keychain.get_secret` and `keychain.store_fernet_key` with an in-memory dict, so tests never touch the real Keychain.
        *   **Opt-out:** it does nothing for tests marked `real_keychain` (checked with `request.node.get_closest_marker("real_keychain")`). `test_keychain.py` sets `pytestmark = pytest.mark.real_keychain` and replaces `subprocess.run` itself.
        *   **Starting content:** an `smtp` entry with the value `test-password`, and no `fernet-key`.
        *   **Test controls:** `fake_keychain.items` (the dict, which tests can change directly) and `fake_keychain.fail_write = True`, which makes `store_fernet_key` raise `StateError("storing the key in the Keychain failed")`.

#### 25. `tests/test_config.py` (Create)

*   **Type / Scope**: Unit tests.
*   **Proposed Changes**:
    *   **Rejected:**
        *   duplicate IDs
        *   duplicate emails that differ only in case
        *   a bad ID format, and `id = "p1\n"`
        *   participant emails `alma.example.org` (no `@`), `alma@example` (no dot in the domain) and `al ma@example.org` (whitespace)
        *   1 or 11 participants
        *   a missing required key
        *   a missing file
        *   a port other than 465 or 587
        *   `mail.from = "Wichteln"` (no address) and `envelope_from = "bounce"`
        *   broken TOML, with a message that contains the file name, "line" and "column"
        *   broken TOML where a duplicated key is a participant's name: the message doesn't contain that name
        *   a Latin-1 file containing an umlaut ("not valid UTF-8")
        *   a folder in place of the file
        *   a missing `participant` array, a table without `name`, and `id = 5`
        *   `port = "465"` (a string)
    *   **Accepted:** the packaged example files.

#### 26. `tests/test_keychain.py` (Create)

*   **Type / Scope**: Unit tests of the real `keychain.py`, with `subprocess.run` replaced. The module sets `pytestmark = pytest.mark.real_keychain`, so the autouse `fake_keychain` stays out of the way.
*   **Proposed Changes**:
    *   **Command path:** every call uses `/usr/bin/security` as the first argument and runs without a shell.
    *   **`get_secret`:**
        *   strips the trailing newline
        *   exit 44 raises `StateError` with the restore hint
        *   exit 51 raises `StateError` containing "51" and no restore hint
    *   **`store_fernet_key`:**
        *   sends the key on standard input and never in the argument list
        *   a matching read-back succeeds
        *   a different read-back value raises `StateError("storing the key in the Keychain failed")`
        *   a read-back that finds no item raises the same, even when `security -i` exited with 0
        *   a value that isn't a Fernet key, including a valid key followed by a newline, raises `ValueError` before any subprocess runs

#### 27. `tests/test_store.py` (Create)

*   **Type / Scope**: Unit tests.
*   **Proposed Changes**:
    *   **Round trip:** saving then loading round-trips a state.
    *   **Encrypted on disk:** this test uses the participant name `participantmarkerxyz`, and the file on disk doesn't contain it. At 20 characters, a chance match in the base64 token is negligible; a 2-character ID like `p1` would appear by chance about one run in ten.
    *   **Errors:**
        *   a wrong key raises `StateError("cannot decrypt…")`
        *   a 10-character key raises `StateError("invalid key format")`
        *   a valid key with an encrypted non-JSON payload raises `StateError("malformed state")`
        *   a payload without a `status` field raises the same
        *   a payload with `format: 2` raises `StateError("unsupported state format")`
        *   a missing `state.enc` raises `StateError` mentioning `--no-history`
    *   **Crash safety:** a crash simulated between writing the temp file and `os.replace` leaves the old file readable.
    *   **File mode:**
        *   after a save, `state.enc` has mode `0o600`; `os.replace` keeps the temp file's mode, so this checks it
        *   a stale `state.enc.tmp` with mode `0o644` is replaced, and the result is still `0o600`

### Phase 4: Emails

#### 28. `src/wichteln/templates.py` (Create)

*   **Type / Scope**: Message building, no I/O.
*   **Proposed Changes**:
    *   **Texts:** module constants holding the subject `Dein Wichtel-Los {year}` and the body lines exactly as listed in the [Emails](#emails) section. The body lines are joined with `\n`, and the event line is left out when it is empty.
    *   **`build_message(mail_cfg, giver: Participant, recipient: Participant, draw: Draw, to_addr: str) -> email.message.EmailMessage`:** `giver` and `recipient` always come from `draw.participants` (the snapshot), so names in the body never change after the draw. `to_addr` is the only value that may come from the current file.
        *   **Headers:** sets these:
            *   `From`, `Reply-To`, and `To` (`to_addr` only)
            *   `Subject`, the fixed subject with `{year}` filled from `draw.year`
            *   `Date`, from `email.utils.formatdate(localtime=True)`
            *   `Message-ID`, from `email.utils.make_msgid(domain=domain)`, where `domain = email.utils.parseaddr(mail_cfg.from_addr)[1].rpartition("@")[2]`. The domain is always passed explicitly, so the laptop's hostname never appears in a header.
            *   `Auto-Submitted: auto-generated` and `X-Auto-Response-Suppress: All`
        *   **Event line:** taken from `draw.event_line`, never from the current config.
        *   **Content:** the body is attached with `msg.set_content(body, cte="quoted-printable")`, so a body with umlauts goes out 7-bit safe through any relay. Tests read the body with `msg.get_content()`.
        *   **Body choice:** uses the replacement body when `draw.replaces` has the giver. With `t = datetime.fromisoformat(ts).astimezone()`, the date is `t.strftime("%d.%m.%Y")` and the time `t.strftime("%H:%M")`.
    *   **`build_test_message(mail_cfg, participant, year)`:** builds the preflight test email, with the same headers as `build_message`, the subject `Wichteln {year}: Test-E-Mail` and these body lines:
        1.  `Hallo {name},`
        2.  an empty line
        3.  `dies ist eine Test-E-Mail für das Wichteln {year}. Sie enthält noch kein Los. Bitte bestätige im Familienchat, dass sie angekommen ist, und füge den Absender zu deinen Kontakten hinzu.`
        4.  an empty line
        5.  the reply line from the [Emails](#emails) section

        It contains no recipient.

#### 29. `src/wichteln/mailer.py` (Create)

*   **Type / Scope**: SMTP sending.
*   **Proposed Changes**:
    *   **`TransportError(Exception)`:**
        *   **Fields:** `step: Literal["connect", "auth", "send"]`, `code: int | None` (the SMTP reply code, if there is one) and `kind: str` (the class name of the original exception).
        *   **No text:** it never stores the original exception's text, recipient address or server message.
        *   **Not a `WichtelnError`:** it stays inside the mailer and `cli`.
    *   **`Transport` protocol:**
        *   **`login() -> None`:** opens the connection and logs in. Raises `TransportError` with step `connect` or `auth`.
        *   **`send(msg: EmailMessage) -> None`:** sends one message. Raises `TransportError` with step `connect` if the connection was lost, or `send` otherwise.
        *   **`close() -> None`:** ends the session. It never raises.
    *   **`SmtpTransport(smtp_cfg: SmtpConfig, password: str, envelope_from: str)`:** implements the protocol. It holds the envelope sender, so callers don't pass it per message. It never reconnects: a failed message stays pending, and the admin runs `send` again.
        *   **`login()`:**
            *   **Port 465:** `smtplib.SMTP_SSL(host, port, context=ssl.create_default_context(), timeout=30)`.
            *   **Port 587:** `smtplib.SMTP(host, port, timeout=30)`, then `starttls(context=ssl.create_default_context())`. Errors from `starttls` are never caught to carry on; they become step `connect`, so nothing is ever sent without encryption.
            *   **Logging in:** then `login(username, password)`.
            *   **Error mapping:** `SMTPAuthenticationError` becomes step `auth`, with its `smtp_code`. Every other `smtplib.SMTPException` (for example `SMTPNotSupportedError`, `SMTPHeloError`, or a plain `SMTPException` when no login method fits) and every `OSError` becomes step `connect`.
        *   **`send(msg)`:** calls `send_message(msg, from_addr=envelope_from)`.
            *   **Lost connection (`SMTPServerDisconnected`, `OSError`, timeouts):** step `connect`.
            *   **Refused recipient (`SMTPRecipientsRefused`):** step `send`, with `code` taken from the single entry of `exc.recipients` (a dict of address → `(code, message)`). The address and message are dropped.
            *   **Other `SMTPResponseException`:** step `send`, with `exc.smtp_code`.
            *   **Any other `smtplib.SMTPException`:** step `send`, with `code=None`.
        *   **`close()`:** calls `quit()`; if that raises, calls `close()` on the connection. Errors are ignored.
        *   **No debug output:** it never calls `set_debuglevel`.
    *   **`send_all(transport, messages: dict[str, EmailMessage], on_result: Callable[[str, TransportError | None], None]) -> dict[str, TransportError | None]`:** calls `on_result` after every message (and for every message on a login failure), and maps each giver ID to `None` (accepted) or its error.
        1.  Call `transport.login()`. If it raises, every message gets that error and nothing is sent. A connect or auth failure marks every message failed after one attempt, instead of waiting for a 30-second timeout per message.
        2.  Send the messages in giver-ID order. A `TransportError` with step `send` affects only that message.
        3.  If a send raises a `TransportError` with step `connect`, that message and all remaining messages get that error without further attempts.
        4.  Always call `transport.close()` at the end.

#### 30. `tests/conftest.py` (Modify)

*   **Type / Scope**: Test fixtures for Phase 4.
*   **Proposed Changes**: Adds `fake_transport`, an implementation of the `Transport` protocol that records messages. It is used by the CLI tests (exit code 2, resume with `send`) and by the `send_all` tests. It can be set to:
    *   fail `login()` with `TransportError("connect", ...)` or `TransportError("auth", 535, ...)`
    *   refuse chosen addresses with `TransportError("send", 550, ...)`
    *   raise `TransportError("connect", ...)` after a given number of messages, to test that `send_all` marks the rest failed

#### 31. `tests/test_templates.py` (Create)

*   **Type / Scope**: Unit tests.
*   **Proposed Changes**:
    *   **Headers:**
        *   the message has exactly one `To` (`to_addr`), no `Cc` or `Bcc`, `Reply-To` set, and both auto-reply headers
        *   `Message-ID` ends with `@example.org>`
        *   the subject is `Dein Wichtel-Los 2026` and contains no name
        *   `Content-Transfer-Encoding` is `quoted-printable`
    *   **Body** (read with `get_content()`):
        *   the names come from the snapshot even when `to_addr` differs from the snapshot email
        *   the event line comes from the draw
        *   an empty `event_line` leaves no double blank line
    *   **Replacement body:** used only when `replaces` has the giver, and contains the date in `dd.mm.yyyy` format and the time in `HH:MM` format, in the pinned time zone.
    *   **Test message:** has the greeting once, the test sentence and the reply line, and contains no other participant's name.

#### 32. `tests/test_mailer.py` (Create)

*   **Type / Scope**: Unit tests with `smtplib` replaced.
*   **Proposed Changes**:
    *   **Port choice:** port 465 uses `SMTP_SSL`, and 587 uses `starttls`.
    *   **Encryption:**
        *   a `starttls` failure gives step `connect`
        *   nothing is sent
    *   **Login failures:**
        *   `SMTPAuthenticationError` gives step `auth` with its code, and `send_all` marks every message with it after one login attempt
        *   `SMTPNotSupportedError` and a plain `SMTPException` from `login()` give step `connect`
        *   a connect timeout in `login()` marks every message with step `connect`, after one attempt only
    *   **Refused recipient:**
        *   gives step `send` and code 550 from `exc.recipients`
        *   the other messages are still sent
    *   **Lost connection:** `SMTPServerDisconnected` or a timeout during a send gives step `connect`, and `send_all` marks the remaining messages failed without trying them.
    *   **Order:** messages are sent in giver-ID order.
    *   **No text kept:** no `TransportError` contains the address or the server message.
    *   **Closing:**
        *   `close()` is called after every `send_all`, including after a login failure
        *   an exception from `quit()` is swallowed, and the connection is closed

### Phase 5: Command line and documentation

#### 33. `src/wichteln/cli.py` (Modify: replaces the Phase 1 stub)

*   **Type / Scope**: Command-line interface (`argparse`).
*   **Proposed Changes**:
    *   **Seams:** tests replace these module-level functions:
        *   **`main(argv=None)`:** the entry point.
        *   **`make_transport(smtp_cfg, password, envelope_from)`:** creates the transport.
        *   **`make_rng()`:** returns `secrets.SystemRandom()`.
        *   **`current_year()`:** returns `datetime.date.today().year`, the only source of "this year".
        *   **`confirm(question: str) -> bool`:**
            1.  Returns `False` without asking if `sys.stdin.isatty()` is false.
            2.  Otherwise writes `question` and a space to stderr, then reads one line from stdin.
            3.  Returns `True` only for `y` or `Y`. `EOFError` or `OSError` count as `False`.

        `cli` calls `solver`, `store`, `mailer`, `config`, `templates` and `keychain` through their modules (for example `solver.build_draw(...)`), never with `from … import`, so tests can replace them.
    *   **Parser:**
        *   **Usage errors:** an `ArgumentParser` subclass whose `error()` raises `UsageError`, so usage errors exit with 1, not argparse's 2.
        *   **Subcommands:** created with `add_subparsers(dest="command", required=True)`, so a bare `wichteln` is a usage error.
        *   **Flags:** `draw` has `--redraw`, `--no-history` and `--yes`; `dropout` has `--yes`; `preflight` has `--test-email`. There is no year option.
    *   **Error handling in `main()`:**
        *   **Tool errors:** a `WichtelnError` prints its message and exits with its code.
        *   **Ctrl-C:** a `KeyboardInterrupt` prints "cancelled" and exits with 1.
        *   **Anything else:** prints only `internal error: <ClassName>` and exits with 1.
        *   **Return value and streams:** `main` returns the exit code; the console script passes it to `sys.exit`. Results go to stdout, and errors, warnings and questions go to stderr.
    *   **Output lines** (stdout unless noted):
        *   **History line:** `history: <id>, <id>`, at most the first two draws from `history_before`, or `history: none`.
        *   **Relaxation line:** `relaxation: <level>`.
        *   **Draw line:** `draw: <draw_id>`, printed by `send`, `dropout` and `status` for the draw they act on.
        *   **Send summary:** `<prefix>sent X of N`, then one failure line per failed giver: `<giver id>: <step> failed (<code or kind>)`.
        *   **`status`:** the draw line, the relaxation line, one line per giver `<giver id>: accepted|failed|pending`, and `not in draw: <ids>` when the file has IDs the draw doesn't.
    *   **Name rule:** no output line contains a participant's name, except the `dropout` question, which contains the dropout's own name. Addresses, giver IDs and draw IDs may appear, because none of them reveals a match.
    *   **Loading key and state:** `load_context(allow_missing_state: bool = False) -> tuple[bytes, State]` applies the rules in [Backup and recovery](#backup-and-recovery) and is used by `draw`, `send`, `dropout`, `status` and the `preflight` state check. Every failure raises `StateError` (exit 3). `allow_missing_state` is set only by `draw --no-history`, which then gets an empty state.
    *   **Finding the draw:** `send`, `dropout` and `status` act on `state.latest_final()`. If there is none, they raise `UsageError("no final draw found; run wichteln draw first")`.
    *   **Addresses after the draw:**
        *   **Reading the file:** `send`, `dropout` and `status` try `config.load_participants`.
        *   **On failure:** if it raises `ConfigError`, they print `warning: participants.toml unreadable (<message>); using addresses from the draw` and use the snapshot addresses.
        *   **On success:** a giver's `to_addr` is the snapshot's email unless the file has a different email for that ID. In that case, before any message is built, the command calls `confirm(f"{id}: address changed from {old} to {new}. Send to the new address? [y/N]")` once per such giver.
            *   **`True`:** send to the new address. Once that send is accepted, replace the giver's snapshot entry with `dataclasses.replace(participant, email=new)`, so later runs don't ask again.
            *   **`False`:** send to the snapshot address and print `<id>: using the address stored in the draw` to stderr.
            *   **`--yes` doesn't answer this question.** It only answers the `dropout` and `--redraw` questions, so skipping one prompt never silently accepts a changed address.
        *   **No validation stop:** after the draw these commands never stop because of the file.
    *   **Sending:** one helper, `send_to(key, state, draw, giver_ids, to_addrs, new_addrs, smtp_cfg, mail_cfg, password, prefix="")`, used by every sending path. All inputs are fetched by the command before anything is saved. It:
        1.  Builds one message per giver in `giver_ids` with `templates.build_message(..., to_addr=to_addrs[giver])`.
        2.  Creates the transport with `make_transport(...)` and calls `mailer.send_all`.
        3.  Records each result in `on_result`, with `now_utc()` as the time:
            *   **Accepted:** sets `result`, `at` and `accepted_at`, and stores a confirmed new address from `new_addrs` in the snapshot.
            *   **Failed:** sets `result` and `at` and keeps the previous `accepted_at`.

            It calls `store.save` after every message, so a crash re-sends at most one email.
        4.  Prints the send summary line and the failure lines. The summary is printed whether or not sends failed.
        5.  Raises `SendFailures(f"{failed} of {total} emails failed")` if any failed. The command prints nothing after the sending step.

    Per command:
    *   **`init`:**
        1.  Create the data folder if missing, and copy the packaged example files if absent. Existing files are never overwritten.
        2.  If neither the `fernet-key` nor `state.enc` exists:
            1.  Generate a key with `Fernet.generate_key()` and store it with `keychain.store_fernet_key`, which verifies it by reading it back. If storing fails, the `StateError` stops the command before any state is written or any key is printed.
            2.  Print the key once, with the instruction to save it in the password manager and then clear the terminal scrollback (Cmd-K).
            3.  Only then write an empty state (`format: 1`, no draws). If this fails, the key has already been shown, and the next `init` reports the missing state.
        3.  If both exist, load the state with the key to check that they belong together, and print `nothing to do: key and state.enc exist`.
        4.  If only one of them exists, `load_context` raises the matching `StateError`.
    *   **`preflight [--test-email]`:**
        *   **Checks:** runs these in order. Each prints `<check>: OK`, `<check>: FAILED (<message>)` or `<check>: skipped (needs <check>)`:
            1.  `participants` (`config.load_participants`)
            2.  `config` (`config.load_config`)
            3.  `state` (`load_context`, with its `StateError` message as the error)
            4.  `smtp` (skipped if `config` failed): fetch the password, create the transport, call `login()` then `close()`, sending nothing. A missing or unreadable password prints its `StateError` message. A login failure prints `<step> failed (<code or kind>)`.
            5.  `draw` (skipped if `participants` or `state` failed): call `solver.solve_with_relaxation` with `make_rng()` for `current_year()` and discard the matches. Print the history line and the relaxation line.
            6.  `test-email` (only with `--test-email`; skipped if `participants`, `config` or `smtp` failed): sends the test message to every participant with `mailer.send_all` and prints `<id>: accepted` or the failure line per ID. Any failed message counts as a failed check.
        *   **File mismatches:** if a final draw exists, prints `not in draw: <ids>` for IDs in the file that aren't in `latest_final()`.
        *   **Exit:** if any check failed, raises `UsageError(f"preflight: {n} checks failed")`, which exits with 1.
    *   **`draw [--redraw] [--no-history] [--yes]`:**
        1.  Call `config.load_config`. A `ConfigError` stops the command with exit 1 before anything is read or saved.
        2.  Call `load_context(allow_missing_state=--no-history)`.
        3.  Fetch the SMTP password with `keychain.get_secret(SMTP_ACCOUNT)`. A `StateError` stops the command before anything is saved.
        4.  If `current(current_year())` exists:
            *   **Without `--redraw`:** raise `UsageError("a draw for <year> exists; use wichteln send to finish sending or --redraw to replace it")`.
            *   **With `--redraw`:** call `confirm("Replace draw <draw_id> and email everyone again? [y/N]")` unless `--yes` is given. `False` raises `UsageError("cancelled, nothing changed")`. Otherwise mark it `void` and remember it.
        5.  Load the participants and call `solver.build_draw(state, current_year(), participants, voided, mail_cfg.event_line, make_rng(), now_utc())`. Print the history line and the relaxation line. Append the new draw and save.
        6.  Send to all participants.
    *   **`send [<id>]`:**
        1.  Call `config.load_config`. A `ConfigError` stops the command with exit 1 and sends nothing.
        2.  Call `load_context()` and find the draw. Print the draw line.
        3.  Choose who to send to:
            *   **Without `<id>`:** send to `draw.pending()`. If none is pending, print `nothing to send` and exit with 0.
            *   **With `<id>`:** raise `UsageError("unknown participant <id>")` if `<id>` isn't in the draw, otherwise send to that giver.
        4.  Work out the addresses (and ask about changed ones), fetch the SMTP password, then send.
    *   **`dropout <id> [--yes]`:**
        1.  Call `config.load_config`. A `ConfigError` stops the command with exit 1 and changes nothing.
        2.  Call `load_context()` and find the draw. Print the draw line.
        3.  Follow Dropout splice steps 1 to 3:
            *   **Unknown ID:** `UsageError("unknown participant <id>")`.
            *   **Too few left:** `UsageError("fewer than 2 participants would remain")`.
            *   **Question:** `confirm("Remove <name> (<id>) from draw <draw_id>? [y/N]")` with the dropout's name from the snapshot, unless `--yes` is given. `False` raises `UsageError("cancelled, nothing changed")`.
        4.  Fetch the SMTP password.
        5.  Follow Dropout splice steps 4 to 6, using `rules.forbidden_pairs(state.history_before(draw.year), draw.relaxed)` and `splice.splice_out`. The full re-draw calls `solver.build_draw(state, draw.year, snapshot minus D, voided=draw, event_line=draw.event_line, make_rng(), now_utc())` and prints the history line and the relaxation line.
        6.  Work out the addresses for `draw.pending()` (asking about changed ones), then send with `prefix="spliced; "` or `prefix="full re-draw; "`.
    *   **`status`:** call `load_context()` and find the draw. Print the status lines. `status` doesn't load `config.toml`.

#### 34. `tests/conftest.py` (Modify)

*   **Type / Scope**: Test fixtures for Phase 5.
*   **Proposed Changes**:
    *   `rng` replaces `cli.make_rng` with one returning `random.Random(seed)`.
    *   `answers` replaces `cli.confirm` with a function that pops the next answer from a list the test sets (default: an empty list, meaning every question is answered `False`, as with no terminal). It records each question, so tests can check the question text.
    *   `year` replaces `cli.current_year` with a function returning a value the test sets (default 2026).
    *   An autouse wiring makes `cli.make_transport` return the `fake_transport` from item 30.
    *   `assert_no_name_leak(output, state, allowed=None)` checks the name rule from item 33: no participant name in any captured line, except `allowed`, the dropout's name in the `dropout` question line.

#### 35. `tests/test_cli.py` (Create)

*   **Type / Scope**: End-to-end tests of the commands, using the fake keychain, fake transport, seeded random source, the `answers` and `year` fixtures, and the pinned time zone.
*   **Proposed Changes**:
    *   **`init`:**
        *   `init` then `draw` sends N messages and stores one final draw.
        *   `init` run a second time overwrites nothing, prints no key and prints `nothing to do: key and state.enc exist`.
        *   `init` with `state.enc` but no key exits with 3.
        *   `init` with a key but no `state.enc` exits with 3.
        *   `init` whose Keychain write fails exits with 3, writes no `state.enc` and prints no key.
    *   **Key lost for good:** moving `state.enc` aside and deleting the key, then running `init` and `draw`, succeeds with empty history and prints `history: none`.
    *   **Missing key or state:**
        *   `send`, `dropout` and `status` with a key but no `state.enc` exit with 3.
        *   The same commands with both missing exit with 3.
        *   `draw` with `state.enc` present but no key exits with 3.
        *   `draw` with neither exits with 3 and mentions `wichteln init`.
        *   A malformed `state.enc` exits with 3 and prints "malformed state".
    *   **`draw`:**
        *   `draw` without an SMTP password exits with 3 and stores no new draw.
        *   `draw` with a broken `config.toml` exits with 1 and stores no new draw.
        *   A second `draw` exits with 1 and mentions `send`.
        *   `draw --redraw` with the answer `n` (or no answer) exits with 1 and leaves the first draw `final`.
        *   `draw --redraw --yes` voids the first draw. Participants with an accepted send get the replacement body, and the others get the normal body.
        *   A missing `state.enc` without `--no-history` exits with 3. With `--no-history` it draws.
        *   `draw` prints the history line with the IDs of the two previous final draws.
    *   **`send`:**
        *   A partial send failure exits with 2 and ends with "N of M emails failed". A following `send` sends only the failed ones.
        *   `send` with a broken `config.toml` exits with 1 and sends nothing.
        *   A login failure exits with 2, leaves the draw stored, and makes exactly one login attempt.
        *   `send <id>` sends one message with the same body as the original.
        *   A resend after `mail.event_line` was changed in `config.toml` has exactly the original body.
        *   A name changed in the file doesn't change the body.
        *   **Changed address:** after the draw, the file has a new address for one giver.
            *   With the answer `y`, `send <id>` sends to the new address with the same body and stores it, so a second `send <id>` asks nothing.
            *   With the answer `n`, or no answer, it sends to the stored address and prints `<id>: using the address stored in the draw`.
            *   Two swapped addresses are never used without a `y`.
        *   `send` with a `participants.toml` that fails a shape check prints the warning and sends to the stored addresses.
        *   `send <id>` with an unknown ID exits with 1.
        *   `send` with nothing pending prints `nothing to send` and exits with 0.
        *   With the year set to 2027, `send` finds the 2026 draw and prints `draw: 2026-1`.
    *   **`dropout`:**
        *   With the answer `y`, a dropout on a draw that can be spliced sends exactly one message and prints "spliced; sent 1 of 1".
        *   **Regression test:** after a splice, failing G's send and then running `send` sends exactly one message.
        *   After a splice, `replaces` has no entry for D.
        *   A splice where G had a failed send keeps G's earlier `replaces` entry.
        *   A splice while another giver is still pending from an earlier failure prints "spliced; sent 2 of 2".
        *   A splice whose one email fails prints exactly one summary line, "spliced; sent 0 of 1", then the failure line, and exits with 2.
        *   A dropout on a mutual pair triggers a full re-draw with N-1 messages.
        *   A dropout where G→R is forbidden at the stored level triggers a full re-draw.
        *   A full re-draw of the 2026 draw run with the year set to 2027 creates draw `2026-2` with `year: 2026` and the voided draw's `event_line`.
        *   In a full re-draw, `replaces` is carried over for givers without an accepted send.
        *   **Failed resend keeps the date:** G's first email is accepted, a later `send G` fails, then a splice changes G's match. G gets the replacement body with the date and time of the first email.
        *   A dropout that would leave 1 participant exits with 1 and leaves the state unchanged.
        *   A dropout with an unknown ID exits with 1, without asking anything.
        *   `dropout` with a broken `config.toml` exits with 1 and leaves the state unchanged.
        *   **Confirmation:** the answer `n` exits with 1, leaves the state unchanged and sends nothing. With `--yes` it proceeds without asking. With no answer (no terminal) and without `--yes` it exits with 1. The recorded question contains the dropout's name and no other participant's name.
    *   **`preflight`:**
        *   With a broken config it reports every failing check, marks the dependent checks `skipped`, and exits with 1.
        *   Its SMTP check calls `login()` and `close()` and sends nothing.
        *   With no SMTP password it prints `smtp: FAILED (...)` with the restore hint and exits with 1.
        *   With no key it reports the `state` check as failed, skips the `draw` check, and exits with 1.
        *   `--test-email` with one refused address exits with 1.
        *   `--test-email` messages contain no other participant's name.
    *   **`status` and others:**
        *   `status` prints the draw line, the relaxation line and one line per giver, and nothing else about matches.
        *   `status` and `preflight` print `not in draw: p9` when the file has an ID `p9` that the draw doesn't.
        *   `send`, `dropout` and `status` without a final draw exit with 1.
        *   A usage error exits with 1, and so does a bare `wichteln`.
        *   **Unexpected exception:** a monkeypatched `solver.build_draw` raising `RuntimeError("Alma")` makes `draw` print exactly `internal error: RuntimeError`, without "Alma", and exit with 1.
        *   A `KeyboardInterrupt` exits with 1 and prints "cancelled".
    *   **Name rule:** every test above passes its captured stdout and stderr to `assert_no_name_leak`.
    *   **History over time:** with the year set to 2026, 2027 and 2028, three draws with 6 participants never repeat a directed match from the two previous final draws, and each of the three draws has `relaxed == "none"`.

#### 36. `README.md` (Create)

*   **Type / Scope**: User documentation.
*   **Proposed Changes**:
    *   **Install:** `uv python install 3.12`, then `uv tool install --python 3.12 --managed-python .`.
    *   **Prerequisites:**
        *   **SMTP account:** an account at any provider, entered in `config.toml`. For G5, the account is used only for Wichteln, and its mailbox, including the Sent folder, replies and bounces, isn't read routinely by the admin.
        *   **Spam protection:** set up SPF, DKIM and DMARC for the sending domain, where the provider allows it.
        *   **Backup:** check that the laptop backup covers the data folder.
    *   **First-time setup:**
        1.  Run `wichteln init`, store the printed key in the password manager, and clear the terminal scrollback.
        2.  Add the SMTP password with `security add-generic-password -s wichteln -a smtp -U -w`, which prompts for it. The password must be printable ASCII, because `security -w` prints other passwords as hex.
        3.  Edit the two files.
    *   **Data folder:** its layout, and the `WICHTELN_HOME` override.
    *   **Yearly runbook:**
        1.  In November, at least two weeks before the planned draw: run `wichteln preflight`. If the tool fails to start, run `uv tool install --reinstall --python 3.12 --managed-python .`.
        2.  Update `participants.toml`.
        3.  Run `wichteln preflight --test-email` and fix any bounced addresses.
        4.  In the family chat, ask everyone to confirm they received the test email, check their spam folder, and add the sender to their contacts.
        5.  Run `wichteln draw` once everyone has confirmed.
        6.  When someone drops out, run `wichteln dropout <id>` and tell them directly.
        7.  When someone loses their email, run `wichteln send <id>`.
        8.  After the gift exchange, delete everything in the Wichteln mailbox, including the Sent folder, without opening it, or turn on the provider's automatic deletion. It may hold late bounces and replies that quote matches.
    *   **Recovery:**
        *   **Lost Keychain key:** `security add-generic-password -s wichteln -a fernet-key -U -w`, which prompts for the key from the password manager.
        *   **Key lost for good:**
            1.  Move `state.enc` out of the data folder.
            2.  If a damaged key is still in the Keychain, run `security delete-generic-password -s wichteln -a fernet-key`.
            3.  Run `wichteln init` and store the new key in the password manager.
            4.  Run `wichteln draw`. History is empty, so no earlier matches are excluded this year.
        *   **Damaged `state.enc`:** restore it from the laptop backup.
        *   **"keychain access failed (exit N)":** unlock the login keychain, or run the command from a logged-in desktop session, then try again.
        *   **`smtp: connect failed (SSLCertVerificationError)` in `preflight`:** run the command with `SSL_CERT_FILE=/etc/ssl/cert.pem`, the macOS system certificates.
        *   **`internal error: <Class>`:** run `uv run pytest` in the code repository to find the broken part.

### Verification Plan

*   **Build:** `uv sync` installs the locked environment. `uv build` produces a wheel. Listing the wheel shows `wichteln/examples/participants.toml` and `wichteln/examples/config.toml`.
*   **Unit and end-to-end tests:** `uv run pytest` must pass at the end of every phase.
*   **Linting and formatting:** `uv run ruff check .` and `uv run ruff format --check .` must pass at the end of every phase.
*   **Test coverage** (checked at the end of Phase 5):
    *   **Overall:** `uv run pytest --cov=wichteln --cov-report=term-missing --cov-fail-under=85` must pass. Branch coverage is on through `[tool.coverage.run]`.
    *   **Draw logic:** `uv run coverage report --include="src/wichteln/solver.py,src/wichteln/splice.py,src/wichteln/rules.py" --fail-under=100` must pass, because an error in these modules produces wrong matches without any error message.
*   **Manual check before the first real draw:** run it before the real `init`, because it uses the same Keychain entries.
    1.  Set `WICHTELN_HOME` to an empty test folder and list 3 addresses the admin controls in its `participants.toml`. Run `init`, `preflight --test-email`, `draw`, `send <id>`, `dropout` and `status`.
    2.  Confirm the following:
        *   the emails arrive and aren't marked as spam
        *   replying to one goes to the Wichteln mailbox
        *   any Sent copies stay in the Wichteln account, not in a mailbox the admin reads
        *   no match appears in the terminal
    3.  Delete the test key with `security delete-generic-password -s wichteln -a fernet-key`, restore it from the password manager copy, and check that `status` still works.
    4.  With the Keychain locked, check that a command reports "keychain access failed" and not the restore hint.
    5.  Delete the test key and the test folder, then run the real `init`.
*   **Success measure after the first season:**
    *   The admin never read or decrypted `state.enc` by hand.
    *   The admin never asked anyone for their match or passed one on.
    *   At most 3 `send <id>` runs were needed in the season.

--------------------------------------------------------------------------------

*Drafted with EGM*
