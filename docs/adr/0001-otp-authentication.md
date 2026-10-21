# ADR-0001: OTP authentication

Status: accepted (MVP). Endpoints and IP throttling are planned for the next PR.

## Context

Customers, organization owners and staff all sign in with a mobile phone number.
A one-time code proves that someone controls a number. That proof must not, by
itself, create organization permissions.

## Decisions

- **`User` is the shared identity for everyone.** Signing in identifies a person
  and grants nothing else. Organization permissions come only from memberships and
  the active tenant, so a staff member who signs in through the customer flow
  gains no extra privileges. Owners will create an organization while
  authenticated and become Admin through a `Membership`; staff will join through
  an invitation bound to their number.
- **Verification proves phone ownership only.** `accounts.otp.verify_otp` returns
  the verified E.164 number and creates nothing. `accounts.customer_auth` turns
  that proof into a user.
- **Codes are scoped by purpose, and every purpose has a policy.** The purpose is
  part of the HMAC input, of the lookup and of the one-open-challenge constraint.
  `otp.POLICIES` holds the limits per purpose (length, validity, attempts,
  cooldown, request cap); an unknown purpose raises `ValueError`, so a new flow
  cannot reuse another flow's rules by accident.
- **Only an HMAC of the code is stored,** keyed with a dedicated `OTP_HMAC_KEY`
  (never `SECRET_KEY`) and compared with `hmac.compare_digest`. The deploy check
  requires at least 32 characters with some variety. This is a heuristic and
  cannot prove entropy; generate the key with `secrets.token_hex(32)`.
- **Challenges are never deleted.** They are closed with a reason (`consumed`,
  `superseded`, `delivery_failed`), which keeps a troubleshooting trail while a
  closed challenge can never be used. A database constraint requires a reason for
  every closed challenge and allows one open challenge per (phone, purpose).
- **Failures are indistinguishable.** Wrong, expired, used, locked and unknown
  codes all raise the same `InvalidOTP`. An inactive account is rejected after the
  code is consumed, with the same error, so account state is not revealed and the
  code cannot be replayed.
- **User creation absorbs only a duplicate-number conflict.** If creation fails
  and the user still does not exist, the original error is re-raised.

## Limits (defaults)

- 6 digits, valid for 120 seconds, 5 wrong attempts per challenge.
- 60 seconds between codes, 5 codes per hour per (phone, purpose). That caps
  guessing at 25 tries per hour per number (about 2.5e-5 chance per hour).
- A failed SMS delivery does not trigger the cooldown but does count toward the
  hourly cap, because the provider may have charged for it.
- Settings are validated by system checks (`accounts.E007`): the code length must
  be between 6 and 10 and every limit must be a positive integer.

## Concurrency

- `request_otp` takes a transaction-level advisory lock per (phone, purpose).
  Row locks are not enough: rows inserted by a concurrent request are invisible to
  a statement already waiting, so the cooldown and the hourly count would be
  stale. With the lock, of N simultaneous requests exactly one creates a challenge
  and sends an SMS; the rest are rejected.
- `verify_otp` locks the open challenge row, so a code is consumed once and the
  attempt counter cannot be exceeded by parallel guesses. The counter is committed
  even when verification fails.
- **PostgreSQL is required.** Advisory locks are PostgreSQL-specific. A system
  check (`accounts.E006`) rejects other databases, and the tests run on real
  PostgreSQL with parallel connections, never SQLite.

## MVP limitations and next PR

- No IP-based limits yet, because the service has no request context. The next PR
  adds the HTTP endpoints with DRF throttling backed by Redis, mapping
  `OTPThrottled` to 429 with `Retry-After` and `InvalidOTP` to a generic 400.
  **The endpoints must not be exposed publicly before IP throttling is in place.**
  Client IP resolution behind a proxy must be configured explicitly.
- Old challenges are kept indefinitely; a periodic cleanup task will come with the
  Celery work.
- Rotating `OTP_HMAC_KEY` invalidates codes in flight (at most two minutes of
  validity), which is acceptable.
- The HTTP SMS backend is generic; it will be adapted once a provider is chosen.
- `manage.py check --deploy` rejects the console SMS backend, a missing, reused or
  weak HMAC key, and an incomplete or non-HTTPS SMS provider configuration.

## Additional guarantees

- **Settings are validated before use.** `otp._settings_policy` rejects invalid
  values (`ImproperlyConfigured`) on every call, because processes such as
  gunicorn never run system checks. `accounts.E007` reports the same problem from
  management commands.
- **Malformed codes count as wrong guesses.** A code that is not an ASCII digit
  string of the expected length is replaced by an empty guess, so it increments the
  attempt counter like any other failure and cannot be used to probe for free.
  The HTTP layer will also validate input.
- **Unique-violation detection is precise.** Concurrent user creation is absorbed
  only for PostgreSQL SQLSTATE 23505 and only if the user now exists.
- **Close failures never hide delivery failures.** If marking a challenge as
  `delivery_failed` itself fails, the original SMS error is still raised and the
  second failure is logged (without the code). The undelivered code expires on its
  own.
- **The SMS backend must subclass `SmsBackend`** (`accounts.E009`); importing a
  module that raises is reported as `accounts.E008` instead of a traceback.
- **SQLite is not supported.** This is a deliberate choice: the concurrency
  guarantees depend on PostgreSQL, and the tests run against it.

## Notes for the HTTP layer

- The service accepts ASCII digits only. The API layer will normalize Persian and
  Arabic-Indic digits to ASCII (users may type them) and validate the input shape
  before calling the service. The service still treats anything malformed as a
  counted wrong guess.
- Duplicate-phone detection relies on psycopg 3 (`.sqlstate`, `.diag`) and on the
  PostgreSQL constraint name `accounts_user_phone_number_key`; a database test
  pins that name.
