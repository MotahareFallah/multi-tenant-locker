# Known gaps

Things this project knowingly does not do, or does at a cost. Each entry says what
happens, why it was accepted and what the fix would be. Nothing here is hidden
behaviour: the decisions behind most of it are in the ADRs.

## Behaviour

### An expired parcel frees its compartment while it is still inside

ADR-0003 says EXPIRED frees the compartment. The database only knows the parcel
is no longer in an occupying state, but the parcel is physically behind the door
until an operator takes it out. Until then a new deposit can be assigned to the
same compartment.

- Mitigation: operators can list what must be removed with
  `GET /parcels/?status=EXPIRED`.
- Fix: a state or flag such as "awaiting removal" that keeps occupying the
  compartment until an operator confirms. It needs its own ADR.

### The idempotency layer stores a plain hash of the request

`request_hash` is a SHA-256 of the request body. For a pickup the body holds a
short numeric code, so somebody who can read the database could recover a
guessed code offline. The hash matters little once the code is spent (a pickup
code is one-time), and no response body ever holds a secret (this is tested), but
it is still weaker than it should be.

- Fix: an HMAC with a server key, like `OTP_HMAC_KEY` for OTP codes.

### A slow pickup can be failed under its own feet

A pickup that stays in PICKUP_IN_PROGRESS longer than `PICKUP_RECOVERY_MINUTES`
(default 5) is moved to PICKUP_FAILED by the recovery task. The limit must be far
longer than any device timeout. If a device is slower than that, the pickup's
final step is refused and the customer gets 409, although the door may have
opened. The parcel is in PICKUP_FAILED and an operator checks it.

- Fix: keep the limit above the real device timeout once a driver exists.

### A crash in the middle of a request blocks that key until it expires

If the process dies after an `Idempotency-Key` was claimed, the key stays
"running". The same request answers 409 `request_in_progress` until
`IDEMPOTENCY_TTL_HOURS` (default 24) passes. The work never runs twice. A client
that needs to go on uses a new key.

### The storage period starts when the parcel is created

`expires_at` is set in `create_parcel`, not at deposit. A parcel that is
deposited late has less time left. `PARCEL_STORAGE_DAYS` counts from creation.

### Wrong pickup codes are counted but not recorded as events

`wrong_code_attempts` is a counter on the parcel. `ParcelEvent` records state
changes only, so the history does not show when or how often a code was guessed.

### Background jobs

- Celery beat must run as exactly one process. The tasks are safe to run twice
  (they go through `transition()` and delete by condition), but two beats waste
  work.
- Every task goes through the organizations one after another and handles every
  overdue row in one run, without a batch limit. That is fine at this size.
- `ParcelEvent` rows are never deleted (ADR-0003 leaves retention open).

### Any signed-in user can activate an organization's schema by slug

Only on the customer path, and only the caller's own parcels are reachable there.
Whether an organization exists is observable: unknown slug gives 404, a known
one gives an empty list. Accepted in ADR-0004; slugs are not secrets.

## Not built

### A real SMS provider

No provider was chosen. `ConsoleSmsBackend` prints messages for local runs, and
`HttpSmsBackend` posts to `SMS_API_URL` with configurable field names. The
deploy check `accounts.E001` refuses the console backend in production. To go
live, pick a provider and either map its field names or add a small
`SmsBackend` subclass. Delivery receipts are not handled, and a failed send is
retried only by the operator re-sending the code (sign-in codes by asking again).

### A real device driver

Only `SimulatedDevice` exists. A driver implements the `DeviceClient` protocol
(`open_door` that does not open twice for the same `command_id`) and is chosen
with `DEVICE_BACKEND`. There is no deploy check yet that refuses the simulator in
production.

### Smaller things

- A public endpoint to create an organization (there is a management command).
- An audit log of membership changes.
- Pagination of the member list.
- Object-level permissions beyond role and ownership of a parcel.
- A faster test suite: each test that needs an organization builds a schema, so
  the full run takes several minutes. `pytest-xdist` with a database per worker
  would help.
