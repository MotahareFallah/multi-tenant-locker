# multi-tenant-locker

Multi-tenant parcel locker management backend. Django, Django REST Framework, PostgreSQL, Celery and Redis.

> Status: the v1 backend is feature-complete. What it knowingly does not do is
> listed in [Known gaps](docs/known-gaps.md).

## Goals

The aim is a backend whose guarantees are testable, not a set of CRUD endpoints:

- **Tenant isolation**: one PostgreSQL schema per organization, selected only from a trusted server-side mapping.
- **Guarded state machine**: parcel status changes only through validated transitions.
- **Failure handling**: device operations are recorded separately from parcel status. A failed or unknown device result never marks a parcel as delivered.
- **Concurrency safety**: two simultaneous pickups of the same parcel cannot both succeed.
- **Idempotency**: repeating a request with the same key does not repeat its side effects.

## Scope (v1)

- Tenant provisioning and context management
- Users, memberships and role-based access (Admin, Operator)
- Lockers with sized compartments, and parcels with a validated state machine
- Device simulator with fault injection (timeout, unknown result)
- Idempotency keys and row locking on pickup
- Celery tasks: parcel expiry, recovery of stuck pickups and cleanup
- Isolation, concurrency and failure tests on real PostgreSQL, plus CI

Deliberately out of scope for v1: notifications beyond the pickup SMS, a full
transactional outbox, an admin UI or front end, billing, and a real SMS provider
and device driver.

## Getting started

Requirements: [uv](https://docs.astral.sh/uv/) and Docker.
PostgreSQL is required; SQLite is deliberately not supported (see ADR-0001).

    cp .env.example .env
    # in .env, set DJANGO_SECRET_KEY and OTP_HMAC_KEY to two different random values
    docker compose up -d
    uv sync
    uv run python manage.py check --database default

PostgreSQL is published on host port 5433 and Redis on 6379.

## Roadmap

- [x] Project skeleton (uv, Django, DRF, SimpleJWT)
- [x] PostgreSQL and Redis via Docker Compose
- [x] Settings loaded from environment
- [x] CI (lint, migration check, tests)
- [x] OTP service (purpose-scoped codes, per-phone limits, deploy checks)
- [x] OTP endpoints with per-IP throttling (Redis-backed)
- [x] Tenancy architecture decision (ADR-0002)
- [x] Tenant provisioning (an Organization and its own schema)
- [x] Tenant context (membership-gated schema activation)
- [x] Users and memberships
- [x] Role-based permissions (Admin and Operator)
- [x] Member management (add, change role, deactivate)
- [x] Lockers and compartments (admin endpoints)
- [x] Parcels and the state machine (ADR-0003)
- [x] Device simulator with fault injection
- [x] Idempotency keys and pickup with row locking
- [x] HTTP API for staff and customers (ADR-0004)
- [x] Celery: expiry, recovery of stuck pickups and cleanup
- [x] Isolation, concurrency and failure test suite
- [ ] A real SMS provider and a real device driver (see Known gaps)

## Authentication

Everyone signs in with a mobile phone number and a one-time code. Verifying a
number proves ownership only; it grants no organization permissions. See
[ADR-0001](docs/adr/0001-otp-authentication.md) for the design, the MVP limits
and the throttling decisions.

Endpoints (under `/api/v1/auth/`): `otp/request/`, `otp/verify/` (returns a JWT
pair), `token/refresh/` (rotates the refresh token) and `token/blacklist/`
(logout).

The OTP endpoints are rate limited per client IP (`OTP_REQUEST_IP_RATE`,
`OTP_VERIFY_IP_RATE`). **Set `TRUSTED_PROXY_COUNT` to the number of reverse
proxies in front of the app** (default `0`: only the socket address is used and
`X-Forwarded-For` is ignored). With the wrong value, either every user shares one
limit (too low) or a forged header can dodge it (too high).
`manage.py check --deploy` warns while it is `0`.

Maintenance: Celery beat runs both cleanups daily (see Background jobs). They can
also be run by hand: `manage.py purge_otp_challenges` deletes old closed or
expired OTP challenges, and SimpleJWT's `manage.py flushexpiredtokens` clears
expired entries from the token blacklist.

## Organizations

Each organization has its own PostgreSQL schema ([ADR-0002](docs/adr/0002-tenancy.md)).
Users, memberships and tokens live in the `public` schema; lockers, parcels and
idempotency keys live in the organization's schema. Apply migrations with
`uv run python manage.py migrate_schemas` (shared apps in `public`, then every
organization's schema). A platform operator creates an organization and its first
admin with:

```bash
uv run python manage.py create_organization --name "Acme" --slug acme --admin-phone 09123456789
```

There is no public endpoint for creating organizations yet.

Tenant endpoints live under `/api/v1/orgs/<slug>/` and are served only to active
members; `GET /api/v1/orgs/<slug>/` returns the organization and the caller's role.
Anyone else gets the same 404 whether the organization exists or not. A member
without the required role gets a 403. `GET /api/v1/orgs/<slug>/members/` lists the
memberships and is for admins only. Admins also add members (`POST` to the same
URL, with a phone number and a role) and change a member's role or active flag
(`PATCH /api/v1/orgs/<slug>/members/<id>/`). Members are never deleted, only
deactivated, and an organization cannot lose its last active admin (409).

## Running locally

A walkthrough of the full flow on a development machine. In development the
SMS backend prints the code to the server log instead of sending it.

```bash
docker compose up -d db redis
uv run python manage.py migrate_schemas
uv run python manage.py create_organization --name "Acme" --slug acme --admin-phone 09123456789
uv run python manage.py runserver 8010   # any free port works
```

In another terminal, request a code for the admin phone:

```bash
curl -s -X POST http://127.0.0.1:8010/api/v1/auth/otp/request/ \
  -H "Content-Type: application/json" -d '{"phone_number": "09123456789"}'
```

The server log shows a line like `DEV SMS to +98...: Your verification code is ...`.
Use that code to sign in:

```bash
curl -s -X POST http://127.0.0.1:8010/api/v1/auth/otp/verify/ \
  -H "Content-Type: application/json" \
  -d '{"phone_number": "09123456789", "code": "<code from the log>"}'
```

The response contains `access` and `refresh` tokens. Call the organization
endpoint with the access token:

```bash
curl -s http://127.0.0.1:8010/api/v1/orgs/acme/ \
  -H "Authorization: Bearer <access token>"
```

It returns the organization's slug and name and your role. A user who is not an
active member of `acme` gets the same `404` as for an organization that does
not exist.
