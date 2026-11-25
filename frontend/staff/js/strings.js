import { ApiError, NetworkError } from "../../js/errors.js";

export { formatWhen } from "../../js/strings.js";

export const text = {
  brand: "Locker staff",
  signOut: "Sign out",
  sessionEnded: "You have been signed out. Sign in again to continue.",
  loading: "Loading…",
  retry: "Try again",
  notMember:
    "This number is not a member of this organization. Sign out and use another number, or ask an admin to add you.",
  footer: "Locker staff",
  parcelsTitle: "Parcels",
  statusFilter: "Status",
  allStatuses: "All statuses",
  showMore: "Show more",
  empty: "No parcels yet.",
  emptyFiltered: "No parcels with this status.",
  columns: ["Tracking code", "Recipient", "Status", "Locker", "Size", "Collect by"],
  newParcel: "New parcel",
  backToParcels: "All parcels",
  lockerLabel: "Locker",
  lockerHelp: "The locker the parcel goes to.",
  recipientLabel: "Recipient's mobile number",
  recipientHelp: "They use this number to sign in and pick the parcel up.",
  sizeLabel: "Size",
  createParcel: "Create parcel",
  creating: "Creating…",
  putInLocker: "Put in locker",
  sendCode: "Send pickup code",
  resendCode: "Send a new pickup code",
  working: "Working…",
  actions: "Actions",
  history: "History",
  historyColumns: ["When", "Change", "By", "Reason"],
  recipient: "Recipient",
  locker: "Locker",
  size: "Size",
  expires: "Collect by",
  added: "Added",
  pickupAttempts: "Pickup attempts",
  wrongCodes: "Wrong codes",
  membersNav: "Members",
  membersTitle: "Members",
  memberColumns: ["Phone number", "Name", "Role", "Status", "Added", "Actions"],
  active: "Active",
  inactive: "Inactive",
  emptyMembers: "No members yet.",
  adminsOnly: "Only admins can manage members.",
  addMemberTitle: "Add a member",
  memberPhoneLabel: "Mobile number",
  memberRoleLabel: "Role",
  addMember: "Add member",
  adding: "Adding…",
  makeAdmin: "Make admin",
  makeOperator: "Make operator",
  deactivate: "Deactivate",
  reactivate: "Reactivate",
  lockersNav: "Lockers",
  lockersTitle: "Lockers",
  lockerColumns: ["Code", "Name", "Address", "Status"],
  emptyLockers: "No lockers yet.",
};

// Staff see the real state names; customers get friendlier words.
const STATUSES = [
  ["CREATED", "Created", "wait"],
  ["STORED", "Stored", "wait"],
  ["READY_FOR_PICKUP", "Ready for pickup", "ready"],
  ["PICKUP_IN_PROGRESS", "Pickup in progress", "wait"],
  ["DELIVERED", "Delivered", "done"],
  ["EXPIRED", "Expired", "alert"],
  ["PICKUP_FAILED", "Pickup failed", "alert"],
];

export const statusOptions = STATUSES.map(([value, label]) => [value, label]);

export function statusOf(status) {
  const found = STATUSES.find(([value]) => value === status);
  return found ? { label: found[1], tone: found[2] } : { label: String(status), tone: "wait" };
}

export const roleText = (role) => ({ admin: "Admin", operator: "Operator" })[role] ?? String(role);

export const countText = (n) => (n === 1 ? "1 parcel" : `${n} parcels`);

export function whereText(parcel) {
  if (parcel.compartment == null) return `${parcel.locker}, no compartment yet`;
  return `${parcel.locker}, compartment ${parcel.compartment}`;
}

const OFFLINE = "Can't reach the server. Check your connection and try again.";

export function organizationMessage(error) {
  if (error instanceof NetworkError) return OFFLINE;
  if (error instanceof ApiError && error.status === 404) return text.notMember;
  return "We couldn't load the organization. Try again.";
}

export function listMessage(error) {
  if (error instanceof NetworkError) return OFFLINE;
  return "We couldn't load the parcels. Try again.";
}

export const sizeOptions = [
  ["SMALL", "Small"],
  ["MEDIUM", "Medium"],
  ["LARGE", "Large"],
];

export const createdText = (parcel) =>
  `Parcel ${parcel.tracking_code} created for ${parcel.recipient_phone}. It is waiting to be put in a locker.`;

// The API's validation errors are {"field": ["message", ...]}: show the messages.
function fieldMessages(body) {
  const parts = [];
  for (const value of Object.values(body ?? {})) {
    if (Array.isArray(value)) parts.push(...value.map(String));
    else if (typeof value === "string") parts.push(value);
  }
  return parts.join(" ");
}

export function createMessage(error) {
  if (error instanceof NetworkError) {
    return "We lost the connection and don't know if the parcel was created. Press the button again; sending it twice is safe.";
  }
  if (error instanceof ApiError) {
    if (error.status === 400) return fieldMessages(error.body) || "Check the details and try again.";
    if (error.status === 409) return error.body?.detail || "The parcel can't be created right now.";
    if (error.status === 403) return "You are not allowed to do this.";
    if (error.status === 429) return "Too many requests. Wait a moment and try again.";
  }
  return "Something went wrong. Try again.";
}

export const depositedText = (parcel) => `Put in ${parcel.locker}, compartment ${parcel.compartment}.`;

export const codeSentText = (parcel) => `A pickup code was texted to ${parcel.recipient_phone}.`;

export function parcelMessage(error) {
  if (error instanceof NetworkError) return OFFLINE;
  if (error instanceof ApiError && error.status === 404) return "We couldn't find this parcel.";
  return "We couldn't load the parcel. Try again.";
}

export function actionMessage(error) {
  if (error instanceof NetworkError) {
    return "We lost the connection and don't know if it went through. Press the button again; sending it twice is safe.";
  }
  if (error instanceof ApiError) {
    if (error.code === "sms_delivery_failed") return "The code could not be sent by text message. Try again.";
    if (error.status === 409) return error.body?.detail || "This can't be done in the parcel's current state.";
    if (error.status === 404) return "We couldn't find this parcel.";
    if (error.status === 403) return "You are not allowed to do this.";
    if (error.status === 429) return "Too many requests. Wait a moment and try again.";
  }
  return "Something went wrong. Try again.";
}

export const memberCountText = (n) => (n === 1 ? "1 member" : `${n} members`);

export function membersMessage(error) {
  if (error instanceof NetworkError) return OFFLINE;
  if (error instanceof ApiError && error.status === 403) return text.adminsOnly;
  return "We couldn't load the members. Try again.";
}

export const memberRoleOptions = [
  ["operator", "Operator"],
  ["admin", "Admin"],
];

export const addedText = (member) => `Added ${member.phone_number} as ${roleText(member.role)}.`;

export function addMemberMessage(error) {
  if (error instanceof NetworkError) {
    return "We lost the connection and don't know if the member was added. Check the list, then try again.";
  }
  if (error instanceof ApiError) {
    if (error.status === 400) return fieldMessages(error.body) || "Check the details and try again.";
    if (error.status === 403) return text.adminsOnly;
    if (error.status === 429) return "Too many requests. Wait a moment and try again.";
  }
  return "Something went wrong. Try again.";
}

export const roleChangedText = (member) => `${member.phone_number} is now ${roleText(member.role)}.`;

export const activeChangedText = (member) => `${member.phone_number} is now ${member.is_active ? "active" : "inactive"}.`;

export function updateMemberMessage(error) {
  if (error instanceof NetworkError) {
    return "We lost the connection and don't know if the change was made. Check the list, then try again.";
  }
  if (error instanceof ApiError) {
    if (error.status === 409) return error.body?.detail || "This change is not allowed.";
    if (error.status === 400) return fieldMessages(error.body) || "Check the details and try again.";
    if (error.status === 404) return "We couldn't find this member.";
    if (error.status === 403) return text.adminsOnly;
    if (error.status === 429) return "Too many requests. Wait a moment and try again.";
  }
  return "Something went wrong. Try again.";
}

export const lockerCountText = (n) => (n === 1 ? "1 locker" : `${n} lockers`);

export function lockersMessage(error) {
  if (error instanceof NetworkError) return OFFLINE;
  if (error instanceof ApiError && error.status === 403) return text.adminsOnly;
  return "We couldn't load the lockers. Try again.";
}
