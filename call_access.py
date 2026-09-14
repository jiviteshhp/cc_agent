"""Ephemeral phone-stream tickets; no accounts, database, or call toggle.

Run the phone app with one worker: /answer and /stream share this process's
memory. Restarting the server invalidates pending tickets, which expire in 60s.
"""

import secrets
import time

_tickets = {}
_TTL = 60
_MAX_PENDING = 128


def issue_ticket(phone):
    now = time.monotonic()
    for token, (_, expires) in list(_tickets.items()):
        if expires <= now:
            del _tickets[token]
    while len(_tickets) >= _MAX_PENDING:
        del _tickets[next(iter(_tickets))]
    token = secrets.token_urlsafe(32)
    _tickets[token] = (phone, now + _TTL)
    return token


def redeem_ticket(token):
    if not token or len(token) > 128:
        return None
    entry = _tickets.pop(token, None)  # consume once, even if expired
    if entry and entry[1] > time.monotonic():
        return entry[0]
    return None
