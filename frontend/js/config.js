// Where the API lives. Change this for a deployed portal and add the portal's own
// origin to CORS_ALLOWED_ORIGINS on the server.
//
// It is deliberately a constant and not read from the URL: a link that could point
// the portal at another server could also send someone's tokens there.
export const API_BASE = "http://127.0.0.1:8010";
