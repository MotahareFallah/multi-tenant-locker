// All user-facing copy lives here, so wording can change (or be translated) in one place.
import { ApiError, NetworkError } from "./errors.js";

export const text = {
  brand: "Locker pickup",
  signOut: "Sign out",
  orgTitle: "Which organization?",
  orgHelp: "Open the link your organization sent you. It ends with ?org= and the organization's name.",
  signInTitle: "Sign in",
  phoneLabel: "Mobile number",
  phoneHelp: "We will text you a 6-digit code.",
  sendCode: "Send code",
  sending: "Sending…",
  codeLabel: "6-digit code",
  verify: "Sign in",
  verifying: "Checking…",
  otherNumber: "Use a different number",
  resend: "Send a new code",
  sessionEnded: "You have been signed out. Sign in again to continue.",
  parcelsTitle: "Your parcels",
  readyGroup: "Ready for pickup",
  otherGroup: "Other parcels",
  empty: "No parcels for this number yet. When one arrives, it will show up here.",
  loading: "Loading…",
  showMore: "Show more",
  retry: "Try again",
  back: "All parcels",
  pickupTitle: "Pick up this parcel",
  pickupLabel: "Pickup code",
  pickupHelp0: "Enter the pickup code you were sent.",
  openDoor: "Open the door",
  opening: "Opening…",
  trackingCode: "Tracking code",
  locker: "Locker",
  compartment: "Compartment",
  size: "Size",
  expires: "Collect by",
  added: "Added",
  notReady: "This parcel is not ready for pickup yet.",
  notReadyDone: "This parcel has already been dealt with.",
  footer: "Locker pickup",
};

export const resendIn = (s) => `Send a new code in ${s}s`;
export const codeSent = (phone) => `We sent a code to ${phone}.`;
export const doorIsOpen = (n) => (n ? `Door ${n} is open. Take your parcel and close the door.` : "The door is open. Take your parcel and close the door.");
export const pickupHelp = text.pickupHelp0;

const STATUS = {
  CREATED: { label: "On its way", tone: "wait", rank: 4 },
  STORED: { label: "In the locker", tone: "wait", rank: 3 },
  READY_FOR_PICKUP: { label: "Ready for pickup", tone: "ready", rank: 0 },
  PICKUP_IN_PROGRESS: { label: "Opening the door", tone: "wait", rank: 2 },
  DELIVERED: { label: "Collected", tone: "done", rank: 5 },
  EXPIRED: { label: "Expired", tone: "alert", rank: 6 },
  PICKUP_FAILED: { label: "Pickup failed", tone: "alert", rank: 1 },
};

export function statusOf(status) {
  return STATUS[status] ?? { label: String(status), tone: "wait", rank: 9 };
}

export function formatWhen(iso) {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(date);
}

export function whereText(parcel) {
  if (!parcel.locker) return "Not placed in a locker yet";
  return parcel.compartment != null ? `${parcel.locker}, compartment ${parcel.compartment}` : parcel.locker;
}

// How long to wait after a 429: the Retry-After header when the browser can read it,
// otherwise the number in the message ("Expected available in 42 seconds.").
export function waitText(error) {
  let seconds = error.retryAfter;
  if (!seconds) {
    const match = /(\d+)\s*second/i.exec(error.body?.detail ?? "");
    seconds = match ? Number(match[1]) : null;
  }
  if (!seconds) return "Wait a moment and try again.";
  return seconds >= 90 ? `Wait about ${Math.ceil(seconds / 60)} minutes and try again.` : `Wait ${seconds} seconds and try again.`;
}

const OFFLINE = "Can't reach the server. Check your connection and try again.";

export function codeRequestMessage(error) {
  if (error instanceof NetworkError) return OFFLINE;
  if (error instanceof ApiError) {
    if (error.status === 429) return `Too many requests. ${waitText(error)}`;
    if (error.status === 400) return "Enter your mobile number, for example 0912 345 6789.";
    if (error.status >= 500) return "We couldn't send the code. Try again in a minute.";
  }
  return "Something went wrong. Try again.";
}

export function verifyMessage(error) {
  if (error instanceof NetworkError) return OFFLINE;
  if (error instanceof ApiError) {
    if (error.status === 429) return `Too many attempts. ${waitText(error)}`;
    if (error.status === 400 || error.status === 401) return "That code is wrong or has expired. Check it, or ask for a new one.";
  }
  return "Something went wrong. Try again.";
}

export function listMessage(error) {
  if (error instanceof NetworkError) return OFFLINE;
  if (error instanceof ApiError && error.status === 404) return "We couldn't find this organization. Check the link you were given.";
  return "We couldn't load your parcels. Try again.";
}

export function parcelMessage(error) {
  if (error instanceof NetworkError) return OFFLINE;
  if (error instanceof ApiError && error.status === 404) return "We couldn't find this parcel for your number.";
  return "We couldn't load this parcel. Try again.";
}

export function pickupMessage(error) {
  if (error instanceof NetworkError) return "We lost the connection and don't know if the door opened. Try again; sending it twice is safe.";
  if (error instanceof ApiError) {
    switch (error.code) {
      case "wrong_pickup_code": {
        const left = error.body?.attempts_left;
        return left == null ? "That pickup code is wrong." : `That pickup code is wrong. ${left} ${left === 1 ? "attempt" : "attempts"} left.`;
      }
      case "pickup_blocked":
        return "Too many wrong codes. Pickup is blocked for this parcel. Contact the organization.";
      case "device_timeout":
        return "The locker did not answer. Try again in a moment.";
      case "device_fault":
        return "The locker could not open the door. Contact the organization.";
      default:
    }
    if (error.status === 429) return `Too many attempts. ${waitText(error)}`;
    if (error.status === 404) return "We couldn't find this parcel for your number.";
    if (error.status === 409) return "This parcel can't be picked up in its current state.";
    if (error.status === 400) return "Enter the pickup code you were sent.";
  }
  return "Something went wrong. Try again.";
}
