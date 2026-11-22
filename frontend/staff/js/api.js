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
