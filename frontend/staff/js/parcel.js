import { h, show } from "../../js/dom.js";
import { ApiError, NetworkError, SessionEnded } from "../../js/errors.js";
import * as api from "./api.js";
import * as s from "./strings.js";

const { text } = s;

const DEPOSIT = { name: "deposit", label: text.putInLocker, run: api.depositParcel, done: s.depositedText };
const SEND_CODE = { name: "pickup-code", label: text.sendCode, run: api.sendPickupCode, done: s.codeSentText };
const RESEND_CODE = { ...SEND_CODE, label: text.resendCode };

// What an operator can do in each state. The server decides what is allowed; this
// only hides what makes no sense.
const ACTIONS = {
  CREATED: [DEPOSIT],
  STORED: [SEND_CODE],
  READY_FOR_PICKUP: [RESEND_CODE],
  PICKUP_FAILED: [RESEND_CODE],
};

const note = (kind, body) => h("p", { class: `message message--${kind}`, role: kind === "error" ? "alert" : "status" }, body);

// One parcel: its facts, what can be done with it, and its history.
export function parcelView(app, trackingCode) {
  app.wide(true);
  const token = app.token;
  const keys = {};
  const back = h("a", { class: "back", href: "#/" }, text.backToParcels);

  async function load(message) {
    try {
      const parcel = await api.getParcel(app.org, trackingCode);
      if (app.token !== token) return;
      render(parcel, message);
    } catch (error) {
      if (app.token !== token) return;
      if (error instanceof SessionEnded) return app.signedOut(text.sessionEnded);
      const missing = error instanceof ApiError && error.status === 404;
      show(
        app.root,
        back,
        note("error", s.parcelMessage(error)),
        missing ? null : h("button", { class: "button", type: "button", onclick: () => load() }, text.retry),
      );
    }
  }

  function facts(parcel) {
    const rows = [
      [text.recipient, parcel.recipient_phone],
      [text.locker, s.whereText(parcel)],
      [text.size, String(parcel.size).toLowerCase()],
      [text.expires, s.formatWhen(parcel.expires_at) || "–"],
      [text.added, s.formatWhen(parcel.created_at) || "–"],
      [text.pickupAttempts, parcel.pickup_attempts],
      [text.wrongCodes, parcel.wrong_code_attempts],
    ];
    return h("dl", { class: "facts" }, rows.map(([name, value]) => [h("dt", {}, name), h("dd", {}, String(value))]));
  }

  function history(events) {
    if (events.length === 0) return null;
    const newestFirst = [...events].sort((a, b) => new Date(b.created_at) - new Date(a.created_at));
    const label = (status) => (status ? s.statusOf(status).label : "–");
    return h(
      "section",
      {},
      h("h2", {}, text.history),
      h(
        "div",
        { class: "table-wrap" },
        h(
          "table",
          { class: "table", "aria-label": text.history },
          h("thead", {}, h("tr", {}, text.historyColumns.map((name) => h("th", { scope: "col" }, name)))),
          h(
            "tbody",
            {},
            newestFirst.map((event) =>
              h(
                "tr",
                {},
                h("td", {}, s.formatWhen(event.created_at)),
                h("td", {}, `${label(event.from_status)} → ${label(event.to_status)}`),
                h("td", {}, event.actor || "–"),
                h("td", {}, event.reason || "–"),
              ),
            ),
          ),
        ),
      ),
    );
  }

  async function perform(action, button, feedback) {
    // The same action after an unknown outcome reuses its key, so it runs only once.
    keys[action.name] ??= api.newIdempotencyKey();
    const label = button.textContent;
    button.disabled = true;
    button.textContent = text.working;
    show(feedback, null);
    try {
      const updated = await action.run(app.org, trackingCode, keys[action.name]);
      delete keys[action.name];
      if (app.token !== token) return;
      await load(note("ok", action.done(updated)));
    } catch (error) {
      if (app.token !== token) return;
      if (error instanceof SessionEnded) return app.signedOut(text.sessionEnded);
      if (!(error instanceof NetworkError)) delete keys[action.name]; // a definite answer
      const failure = note("error", s.actionMessage(error));
      // The parcel may have changed elsewhere: show it as it is now.
      if (error instanceof ApiError && error.status === 409) return load(failure);
      show(feedback, failure);
      button.disabled = false;
      button.textContent = label;
    }
  }

  function render(parcel, message) {
    if (app.token !== token) return;
    const st = s.statusOf(parcel.status);
    const feedback = h("div", { class: "feedback" });
    const available = ACTIONS[parcel.status] ?? [];
    const buttons = available.map((action) => {
      const button = h("button", { class: "button button--primary", type: "button" }, action.label);
      button.addEventListener("click", () => perform(action, button, feedback));
      return button;
    });
    show(
      app.root,
      back,
      h("h1", {}, parcel.tracking_code),
      h("p", { class: `badge badge--${st.tone}` }, st.label),
      message ?? null,
      facts(parcel),
      available.length ? h("section", {}, h("h2", {}, text.actions), feedback, h("div", { class: "row" }, buttons)) : null,
      history(parcel.events ?? []),
    );
  }

  show(app.root, back, h("p", { class: "hint" }, text.loading));
  load();
}
