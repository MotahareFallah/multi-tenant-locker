// The customer's endpoints. Sign-in, tokens and refresh live in session.js.
import { authed } from "./session.js";

export { hasSession, newIdempotencyKey, requestCode, signOut, verifyCode } from "./session.js";

function parcelsPath(org) {
  return `/api/v1/orgs/${encodeURIComponent(org)}/my/parcels/`;
}

export function listParcels(org, page = 1) {
  return authed(`${parcelsPath(org)}?page=${page}`);
}

export function getParcel(org, trackingCode) {
  return authed(`${parcelsPath(org)}${encodeURIComponent(trackingCode)}/`);
}

// The idempotency key makes a repeated request safe: the server answers the first
// attempt again instead of opening the door twice.
export function pickup(org, trackingCode, code, idempotencyKey) {
  return authed(`${parcelsPath(org)}${encodeURIComponent(trackingCode)}/pickup/`, {
    method: "POST",
    body: { code },
    headers: { "Idempotency-Key": idempotencyKey },
  });
}
