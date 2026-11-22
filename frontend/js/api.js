// Talking to the API: sign-in, token refresh and the customer endpoints.
//
// Tokens: the access token lives only in memory. The refresh token is kept in
// sessionStorage, so a reload keeps the person signed in and closing the tab does
// not. The API rotates the refresh token on every use, so refreshes are
// single-flight: two at once would blacklist each other.
import { API_BASE } from "./config.js";
import { ApiError, NetworkError, SessionEnded } from "./errors.js";

const REFRESH_KEY = "locker.refresh";

let accessToken = null;
let refreshing = null;

function storedRefresh() {
  try {
    return sessionStorage.getItem(REFRESH_KEY);
  } catch {
    return null;
  }
}

function storeRefresh(value) {
  try {
    if (value) sessionStorage.setItem(REFRESH_KEY, value);
    else sessionStorage.removeItem(REFRESH_KEY);
  } catch {
    // Private mode or blocked storage: the session then lasts until reload.
  }
}

export function hasSession() {
  return Boolean(accessToken || storedRefresh());
}

async function send(path, { method = "GET", body, auth = true, headers = {} } = {}) {
  const init = { method, headers: { Accept: "application/json", ...headers } };
  if (body !== undefined) {
    init.headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(body);
  }
  if (auth && accessToken) init.headers.Authorization = `Bearer ${accessToken}`;

  let response;
  try {
    response = await fetch(API_BASE + path, init);
  } catch {
    throw new NetworkError();
  }

  let data = null;
  const raw = await response.text();
  if (raw) {
    try {
      data = JSON.parse(raw);
    } catch {
      data = null;
    }
  }
  if (!response.ok) {
    const wait = Number(response.headers.get("Retry-After")) || null;
    throw new ApiError(response.status, data, wait);
  }
  return data;
}

async function refreshAccess() {
  if (refreshing) return refreshing;
  const refresh = storedRefresh();
  if (!refresh) throw new SessionEnded();
  refreshing = (async () => {
    try {
      const data = await send("/api/v1/auth/token/refresh/", {
        method: "POST",
        body: { refresh },
        auth: false,
      });
      accessToken = data.access;
      if (data.refresh) storeRefresh(data.refresh);
    } catch (error) {
      if (error instanceof ApiError) {
        // The server refused the refresh token: it is expired, used or revoked.
        accessToken = null;
        storeRefresh(null);
        throw new SessionEnded();
      }
      throw error; // A network error says nothing about the session: keep it.
    } finally {
      refreshing = null;
    }
  })();
  return refreshing;
}

// A request that needs a signed-in person. An expired access token is replaced
// once; if that fails the person has to sign in again.
async function authed(path, options) {
  if (!accessToken) await refreshAccess();
  try {
    return await send(path, options);
  } catch (error) {
    if (!(error instanceof ApiError) || error.status !== 401) throw error;
    await refreshAccess();
    return send(path, options);
  }
}

export function requestCode(phone) {
  return send("/api/v1/auth/otp/request/", {
    method: "POST",
    body: { phone_number: phone },
    auth: false,
  });
}

export async function verifyCode(phone, code) {
  const data = await send("/api/v1/auth/otp/verify/", {
    method: "POST",
    body: { phone_number: phone, code },
    auth: false,
  });
  accessToken = data.access;
  storeRefresh(data.refresh);
}

// Sign out revokes the refresh token on the server when it can, and always forgets
// the tokens here.
export async function signOut() {
  const refresh = storedRefresh();
  accessToken = null;
  storeRefresh(null);
  if (!refresh) return;
  try {
    await send("/api/v1/auth/token/blacklist/", {
      method: "POST",
      body: { refresh },
      auth: false,
    });
  } catch {
    // Nothing more to do: the tokens are already gone from this browser.
  }
}

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

export function newIdempotencyKey() {
  if (globalThis.crypto?.randomUUID) return crypto.randomUUID();
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  return Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
}
