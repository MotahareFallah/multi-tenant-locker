// The staff endpoints of one organization. Sign-in and tokens live in the shared
// session module.
import { authed } from "../../js/session.js";

export { hasSession, newIdempotencyKey, signOut } from "../../js/session.js";

function base(org) {
  return `/api/v1/orgs/${encodeURIComponent(org)}`;
}

// The organization's name and the signed-in person's role in it ("admin" or
// "operator"). Someone who is not a member gets a 404.
export function getOrganization(org) {
  return authed(`${base(org)}/`);
}

// One page of the organization's parcels, newest first, optionally of one status.
export function listParcels(org, { status = "", page = 1 } = {}) {
  const query = new URLSearchParams({ page: String(page) });
  if (status) query.set("status", status);
  return authed(`${base(org)}/parcels/?${query}`);
}

// Admins only: the organization's lockers, to pick one when creating a parcel.
export function listLockers(org) {
  return authed(`${base(org)}/lockers/`);
}

// The idempotency key makes a repeated request safe: the server answers the first
// attempt again instead of creating a second parcel.
export function createParcel(org, body, idempotencyKey) {
  return authed(`${base(org)}/parcels/`, {
    method: "POST",
    body,
    headers: { "Idempotency-Key": idempotencyKey },
  });
}
