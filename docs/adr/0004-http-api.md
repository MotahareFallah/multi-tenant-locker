# ADR-0004: HTTP API for lockers, parcels and pickup

Status: proposed

## Context

The services for creating, depositing and picking up parcels exist (ADR-0003) but
nothing exposes them. Two kinds of people call the API:

- **Staff**: members of an organization (admins and operators). They already use
  `/api/v1/orgs/<slug>/...`, where the tenant is chosen from an active membership
  (ADR-0002).
- **Customers**: the recipients of parcels. They are not members of any
  organization. They sign in with their phone number and a one-time code, like
  everyone else (ADR-0001), and collect parcels with a pickup code.

## Decision

### Two families of URLs

Staff endpoints stay under `/api/v1/orgs/<slug>/` and use `TenantViewMixin`:
membership first, then the role. Customer endpoints live under
`/api/v1/orgs/<slug>/my/` and use a separate mixin:

1. The caller must be authenticated.
2. The organization is found by slug. An unknown slug gives 404.
3. Only then is the organization's schema activated.
4. Every query is filtered by `recipient_phone == request.user.phone_number`.
   A parcel of another customer looks exactly like a parcel that does not exist (404).

This extends ADR-0002: a customer enters an organization's schema without a
membership. The only things reachable there are that customer's own parcels. The
staff mixin is unchanged, and a person who is both a member and a customer uses
the two families separately; the customer path ignores roles.

### Endpoints

Parcels are addressed by `tracking_code` (16 random hex characters), never by the
numeric id.

| Who | Method and path | What it does |
|---|---|---|
| Admin | `GET, POST /lockers/` | list and create lockers |
| Admin | `GET, PATCH /lockers/<code>/` | read a locker, switch it on or off |
| Admin | `POST /lockers/<code>/compartments/` | add a compartment |
| Admin | `PATCH /lockers/<code>/compartments/<number>/` | switch a compartment on or off |
| Operator | `POST /parcels/` | create a parcel |
| Operator | `GET /parcels/`, `GET /parcels/<tracking_code>/` | list (paginated, filter by status) and read |
| Operator | `POST /parcels/<tracking_code>/deposit/` | put it into a compartment |
| Operator | `POST /parcels/<tracking_code>/pickup-code/` | issue or re-send the pickup code |
| Customer | `GET /my/parcels/`, `GET /my/parcels/<tracking_code>/` | the customer's own parcels |
| Customer | `POST /my/parcels/<tracking_code>/pickup/` | collect with `{"code": "..."}` |

Admins can do everything operators can (ADR-0002). Lists are paginated from the
start, 50 per page, newest first.

### The pickup code never appears in an HTTP response

The idempotency layer stores responses in the database (ADR-0003). A response with
the code in it would put the code there in plain text. So the rule is general:
**a stored response never contains a secret.** The code goes to the recipient by
SMS and nowhere else; the operator's response only says that it was sent.

`pickup-code` works in three states:

- STORED or PICKUP_FAILED: issue a code and move the parcel to READY_FOR_PICKUP
  (a retry still obeys the attempt limit of ADR-0003);
- READY_FOR_PICKUP: re-send, which makes a new code, replaces the old one and
  resets the wrong-code counter. This is how an operator frees a parcel that was
  blocked by too many wrong codes.

If the SMS cannot be sent, the request fails and the operator repeats it; a re-send
is always possible, so no parcel is left with a code nobody has.

### Idempotency

All state-changing POSTs require an `Idempotency-Key` header: create, deposit,
pickup-code and pickup. A missing or invalid key is 400. The endpoint name used
for the key includes the parcel, for example `parcel.deposit:<tracking_code>`, and
the key belongs to the calling user (ADR-0003).

### Errors

| Situation | Status |
|---|---|
| unknown slug, not a member, someone else's parcel, unknown parcel | 404, always the same body |
| member with too low a role | 403 |
| invalid input | 400 |
| missing or invalid `Idempotency-Key` | 400 |
| same key, different request | 422 |
| same request still running | 409 |
| transition not allowed, no free compartment, locker switched off | 409, with a machine-readable `code` |
| wrong pickup code, or parcel blocked by too many wrong codes | 403, with a `code` (and `attempts_left` for a wrong code) |
| device reported a fault during pickup | 502, parcel is now PICKUP_FAILED |
| device did not answer during pickup | 504, parcel is now PICKUP_FAILED |

Refusals the client may see again (a wrong code, a conflict, a device failure) are
returned by the handler, so they are stored and replayed like successes. Device
failures tell the customer to contact an operator and never claim whether the
door opened.

### Throttling

The customer pickup endpoint gets its own per-IP throttle scope (`pickup`), in
addition to the per-parcel wrong-code limit, so one address cannot walk through
many parcels.

## Consequences

- Any signed-in user can activate any organization's schema through the customer
  path, by slug. The safeguard is that nothing but the caller's own parcels is
  reachable there, and tests must prove it. Whether an organization exists is
  observable (unknown slug gives 404, a known slug gives an empty list); slugs are
  not secrets, so this is accepted.
- The stored hash of a pickup request is derived from a one-time code. It only
  matters once the code is spent, so this is accepted.
- SMS delivery becomes part of the operator flow; a real provider is still needed
  (ADR-0001 left it open).
- Deposit, issue and create each need their own idempotency endpoint names.

## Required tests

- Role matrix: admin, operator, customer and a non-member against every endpoint.
- Customer isolation: another customer's parcel, another organization's parcel
  and an unknown slug all give the same 404.
- Staff and customer paths never mix: a customer cannot reach a staff endpoint and
  a member's role gives nothing on the customer path.
- No response and no stored idempotency body contains a pickup code or its hash.
- Every error row of the table above, with its status and `code`.
- Replay: the same key and body returns the same response and runs nothing twice,
  for deposit, issue and pickup, including a replayed device failure.
- Pagination and the status filter.
- The pickup-code re-send resets the wrong-code counter.

## Order of work

1. This ADR.
2. Locker and compartment endpoints (admin).
3. Parcel endpoints for operators, with SMS delivery of the code and the re-send path.
4. Customer endpoints, the customer mixin and the pickup throttle.
