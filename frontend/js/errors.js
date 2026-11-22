// The server answered with an error status. `code` is the machine-readable code
// the API puts in the body (for example "wrong_pickup_code"), when there is one.
export class ApiError extends Error {
  constructor(status, body, retryAfter = null) {
    super(typeof body?.detail === "string" ? body.detail : `HTTP ${status}`);
    this.status = status;
    this.body = body ?? {};
    this.code = this.body.code ?? null;
    this.retryAfter = retryAfter;
  }
}

// No answer at all: offline, the server is down, or the request was blocked.
export class NetworkError extends Error {
  constructor() {
    super("network");
  }
}

// The refresh token is gone or was refused: the person has to sign in again.
export class SessionEnded extends Error {
  constructor() {
    super("session ended");
  }
}
