# ADR-0001: OTP authentication

Status: accepted (MVP). Endpoints and IP throttling are planned for the next PR.

## Context

Customers, organization owners and staff all sign in with a mobile phone number.
A one-time code proves that someone controls a number. That proof must not, by
itself, create organization permissions.

## Decisions

- **Verification proves phone ownership only.** `accounts.otp.verify_otp` returns
  the verified E.164 number and creates nothing. Customer sign-in
  (`accounts.customer_auth`) turns that proof into a user with no privileges.
  Owners will create an organization while authenticated and become Admin through
  a `Membership`; staff will join through an invitation bound to their number.
- **Codes are scoped by purpose.** The purpose is part of the HMAC input, of the
  lookup and of the one-open-challenge constraint, so a code issued for one flow
  cannot be consumed by another.
- **Only an HMAC of the code is stored,** keyed with a dedicated `OTP_HMAC_KEY`
  (never `SECRET_KEY`) and compared with `hmac.compare_digest`.
- **Challenges are never deleted.** They are closed with a reason (`consumed`,
  `superseded`, `delivery_failed`), which keeps a troubleshooting trail while a
  closed challenge can never be used. A database constraint requires a reason for
  every closed challenge and allows one open challenge per (phone, purpose).
- **Failures are indistinguishable.** Wrong, expired, used, locked and unknown all
  raise the same `InvalidOTP`.

## Limits (defaults)

- 6 digits, valid for 120 seconds, 5 wrong attempts per challenge.
- 60 seconds between codes, 5 codes per hour per (phone, purpose). That caps
  guessing at 25 tries per hour per number (about 2.5e-5 chance per hour).
- A failed SMS delivery does not trigger the cooldown but does count toward the
  hourly cap, because the provider may have charged for it.

## Concurrency

- `request_otp` takes a transaction-level advisory lock per (phone, purpose).
  Row locks are not enough: rows inserted by a concurrent request are invisible to
  a statement already waiting, so the cooldown and the hourly count would be
  stale. With the lock, of N simultaneous requests exactly one creates a challenge
  and sends an SMS; the rest are rejected.
- `verify_otp` locks the open challenge row, so a code is consumed once and the
  attempt counter cannot be exceeded by parallel guesses. The counter is committed
  even when verification fails.
- These guarantees are tested on real PostgreSQL with parallel connections
  (`tests/test_otp_concurrency.py`).

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
- Deploy checks (`manage.py check --deploy`) reject the console SMS backend, a
  missing or reused HMAC key and an incomplete or non-HTTPS SMS provider config.
