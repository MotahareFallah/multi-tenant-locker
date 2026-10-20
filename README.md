# multi-tenant-locker

Multi-tenant parcel locker management backend. Django, Django REST Framework, PostgreSQL, Celery and Redis.

> Status: work in progress.

## Goals

The aim is a backend whose guarantees are testable, not a set of CRUD endpoints:

- **Tenant isolation**: one PostgreSQL schema per organization, selected only from a trusted server-side mapping.
- **Guarded state machine**: parcel status changes only through validated transitions.
- **Failure handling**: device operations are recorded separately from parcel status. A failed or unknown device result never marks a parcel as delivered.
- **Concurrency safety**: two simultaneous pickups of the same parcel cannot both succeed.
- **Idempotency**: repeating a request with the same key does not repeat its side effects.

## Planned scope (v1)

- Tenant provisioning and context management
- Users, memberships and role-based access (Admin, Operator)
- Lockers and parcels with a validated state machine
- Device simulator with fault injection (timeout, unknown result)
- Idempotency keys and row locking on pickup
- Celery task for parcel expiry
- Isolation, concurrency and failure tests on real PostgreSQL, plus CI

Deliberately out of scope for v1: notifications, a full transactional outbox, multi-size lockers, admin UI and billing.

## Getting started

Requirements: [uv](https://docs.astral.sh/uv/) and Docker.

    cp .env.example .env
    # set DJANGO_SECRET_KEY in .env to a random value
    docker compose up -d
    uv sync
    uv run python manage.py check --database default

PostgreSQL is published on host port 5433 and Redis on 6379.

## Roadmap

- [x] Project skeleton (uv, Django, DRF, SimpleJWT)
- [x] PostgreSQL and Redis via Docker Compose
- [x] Settings loaded from environment
- [ ] CI (lint, migration check, tests)
- [ ] Tenancy architecture decision (ADR-0001)
- [ ] Tenant provisioning and context management
- [ ] Users, memberships and RBAC
- [ ] Lockers, parcels and state machine
- [ ] Device simulator, retries and idempotency
- [ ] Celery expiry task
- [ ] Security, concurrency and failure test suite
