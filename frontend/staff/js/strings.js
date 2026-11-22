import { ApiError, NetworkError } from "../../js/errors.js";

export const text = {
  brand: "Locker staff",
  signOut: "Sign out",
  sessionEnded: "You have been signed out. Sign in again to continue.",
  loading: "Loading…",
  retry: "Try again",
  notMember:
    "This number is not a member of this organization. Sign out and use another number, or ask an admin to add you.",
  footer: "Locker staff",
};

export const roleText = (role) => ({ admin: "Admin", operator: "Operator" })[role] ?? String(role);

export function organizationMessage(error) {
  if (error instanceof NetworkError) return "Can't reach the server. Check your connection and try again.";
  if (error instanceof ApiError && error.status === 404) return text.notMember;
  return "We couldn't load the organization. Try again.";
}
