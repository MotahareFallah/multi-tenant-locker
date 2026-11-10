# ADR-0003: Parcel lifecycle (state machine, pickup, idempotency)

Status: proposed

## Context

A parcel moves through a fixed lifecycle between a courier depositing it and a
recipient collecting it. Several actors act on the same parcel at the same
time: the recipient at the locker, a Celery expiry job, retried HTTP requests,
and a physical device that can fail or answer late. Without one authoritative
set of rules, two of them can disagree about what state a parcel is in, and the
only source of truth, the database, ends up wrong.

This ADR fixes the lifecycle rules before any model is written. All data
described here lives in the tenant schema (ADR-0002).

## Decision

### States and allowed transitions

| From | To | Trigger |
|---|---|---|
| CREATED | STORED | Parcel deposited in a compartment |
| STORED | READY_FOR_PICKUP | Pickup code issued to the recipient |
| READY_FOR_PICKUP | PICKUP_IN_PROGRESS | Valid pickup code presented, door open requested |
| PICKUP_IN_PROGRESS | DELIVERED | Device confirms the door opened |
| PICKUP_IN_PROGRESS | PICKUP_FAILED | Device reports a fault or does not answer in time |
| PICKUP_FAILED | READY_FOR_PICKUP | Retry allowed (recipient tries again) |
| STORED, READY_FOR_PICKUP, PICKUP_FAILED | EXPIRED | Storage deadline passed (Celery job) |

DELIVERED and EXPIRED are terminal. Any transition not in the table is
rejected with `InvalidTransition` (HTTP 409).

### One place defines the rules

The table lives in code exactly once (`parcels/state_machine.py`, a dict of
allowed `(from, to)` pairs) and one function applies it. Views, tasks and the
device callback never assign `parcel.status` directly.

`transition(parcel_id, to_state, *, actor, reason="")`:

1. opens a transaction and locks the parcel row with `select_for_update`;
2. checks the transition against the table using the locked row's state, not
   the state the caller read earlier;
3. updates the status and appends a `ParcelEvent` row (from, to, actor, reason,
   time) in the same transaction.

`ParcelEvent` is append-only history. It is how we explain how a parcel got
into its current state.

### Pickup

Pickup is two transactions with the device call between them, so that no
database lock is held while talking to hardware:

1. Lock the parcel, check it is READY_FOR_PICKUP and the code is valid, move it
   to PICKUP_IN_PROGRESS, commit.
2. Call the device to open the door.
3. In a second transaction, record the outcome: DELIVERED or PICKUP_FAILED.

Two simultaneous pickups of one parcel: the second waits on the row lock, then
sees PICKUP_IN_PROGRESS and gets 409. Exactly one door-open request is sent.

A crash between steps 1 and 3 leaves the parcel in PICKUP_IN_PROGRESS. A
periodic recovery task moves parcels stuck there longer than a timeout to
PICKUP_FAILED, so a parcel is never stuck forever.

### Idempotency

State-changing POST endpoints (deposit, pickup) require an `Idempotency-Key`
header. Per tenant schema we store key, endpoint, a hash of the request body,
and the stored response, with a unique constraint on (key, endpoint).

- Same key and same body: return the stored response, do nothing again.
- Same key and different body: reject (422).
- Two concurrent requests with the same key: the unique constraint lets one
  proceed; the other waits for or receives the first one's result.

### Device and fault injection

The device is behind one interface (`open_door(compartment)`). The simulator
implements it and can be told to inject: error, timeout, slow response, and a
duplicate acknowledgement. Tests choose the fault; production code does not
know it is talking to a simulator.

### Expiry

A Celery beat task visits each organization with an explicit `tenant_context`
(ADR-0002: no implicit tenant outside a request) and expires overdue parcels
through `transition()`. It is safe to run twice and safe to race with a pickup:
whichever transition takes the row lock first wins and the other is rejected as
invalid, not applied.

## Consequences

- The rules are testable without HTTP or Celery: call `transition()` directly.
- A recovery task and an expiry task are required, not optional.
- Idempotency adds a table and a header requirement for clients.
- `ParcelEvent` grows with every transition; retention is a later decision.

## Required tests

- Every allowed transition succeeds; every other pair raises `InvalidTransition`.
- Terminal states accept no transition.
- Concurrent pickup of one parcel: exactly one wins, one door-open request.
- Pickup racing with expiry: exactly one outcome, history is consistent.
- Device error, timeout, slow response and duplicate ack each end in a defined
  state (never stuck).
- Same idempotency key twice: one effect; same key with different body: rejected.
- Isolation: a parcel, its events and idempotency keys are invisible to another
  organization.

## Open questions

- A device timeout is ambiguous: the door may have opened. Proposed default is
  PICKUP_FAILED followed by manual or reconciled confirmation. Needs a decision.
- Whether CREATED can expire (a parcel never deposited).
- How many pickup retries before a parcel is blocked.
- Whether the pickup code is a one-time value stored hashed (proposed: yes, as
  with OTP in ADR-0001).
- Locker and compartment model (sizes, assignment) is out of scope here and gets
  its own section when the models are written.

## Order of work

1. This ADR.
2. Locker, compartment, parcel and event models in the tenant schema.
3. `transition()` and its unit tests.
4. Deposit and pickup endpoints with idempotency.
5. Device simulator with fault injection.
6. Celery expiry and recovery tasks.
7. Failure and concurrency suite, then docs.
