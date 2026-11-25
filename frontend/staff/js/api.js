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

// Admins only: one page of the organization's lockers, in code order.
export function listLockers(org, page = 1) {
  return authed(`${base(org)}/lockers/?page=${page}`);
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

export function getParcel(org, trackingCode) {
  return authed(`${base(org)}/parcels/${encodeURIComponent(trackingCode)}/`);
}

function action(org, trackingCode, name, idempotencyKey) {
  return authed(`${base(org)}/parcels/${encodeURIComponent(trackingCode)}/${name}/`, {
    method: "POST",
    headers: { "Idempotency-Key": idempotencyKey },
  });
}

// Put the parcel into a free compartment of its size.
export const depositParcel = (org, trackingCode, key) => action(org, trackingCode, "deposit", key);

// Text a new pickup code to the recipient. The code itself is never in the response.
export const sendPickupCode = (org, trackingCode, key) => action(org, trackingCode, "pickup-code", key);

// Admins only: the organization's members, in the order they were added.
export function listMembers(org, page = 1) {
  return authed(`${base(org)}/members/?page=${page}`);
}

// Admins only: give a phone number a role in the organization. The server creates
// the account if needed and rejects a number that is already a member.
export function addMember(org, body) {
  return authed(`${base(org)}/members/`, { method: "POST", body });
}

// Admins only: change a member's role and/or switch them on or off. Members are
// never deleted. The server refuses to leave the organization without an active admin.
export function updateMember(org, memberId, body) {
  return authed(`${base(org)}/members/${memberId}/`, { method: "PATCH", body });
}

function lockerPath(org, code) {
  return `${base(org)}/lockers/${encodeURIComponent(code)}`;
}

// Admins only: a locker with its compartments, in number order.
export function getLocker(org, code) {
  return authed(`${lockerPath(org, code)}/`);
}

// Admins only: add a locker. Its code is the short name used in URLs and cannot
// be changed later.
export function createLocker(org, body) {
  return authed(`${base(org)}/lockers/`, { method: "POST", body });
}

// Admins only: rename a locker, change its address or switch it on or off.
// Lockers are never deleted.
export function updateLocker(org, code, body) {
  return authed(`${lockerPath(org, code)}/`, { method: "PATCH", body });
}

// Admins only: add a compartment ({ number, size }). Numbers are unique per locker.
export function addCompartment(org, code, body) {
  return authed(`${lockerPath(org, code)}/compartments/`, { method: "POST", body });
}

// Admins only: switch a compartment on or off. Its number and size never change.
export function updateCompartment(org, code, number, body) {
  return authed(`${lockerPath(org, code)}/compartments/${number}/`, { method: "PATCH", body });
}
