import { h, show } from "../../js/dom.js";
import { ApiError, NetworkError, SessionEnded } from "../../js/errors.js";
import * as api from "./api.js";
import * as s from "./strings.js";

const { text } = s;

// A form for a new parcel. Admins pick the locker from a list; operators cannot
// read the list, so they type its code.
export function newParcelView(app) {
  const token = app.token;
  let key = null;
  let lastBody = "";

  const feedback = h("div", { class: "feedback" });
  const recipient = h("input", { class: "input", id: "recipient", type: "tel", inputmode: "tel", autocomplete: "off", required: true });
  const size = h("select", { class: "select", id: "size" }, s.sizeOptions.map(([value, label]) => h("option", { value }, label)));
  let locker = h("input", { class: "input", id: "locker", autocomplete: "off", spellcheck: "false", required: true });
  const lockerBox = h("div", {}, locker);

  async function loadLockers() {
    try {
      const data = await api.listLockers(app.org);
      if (app.token !== token) return;
      const active = (data.results ?? []).filter((item) => item.is_active);
      if (active.length === 0) return; // the text field stays
      locker = h(
        "select",
        { class: "select", id: "locker", required: true },
        active.map((item) => h("option", { value: item.code }, `${item.name} (${item.code})`)),
      );
      lockerBox.replaceChildren(locker);
    } catch (error) {
      if (error instanceof SessionEnded && app.token === token) app.signedOut(text.sessionEnded);
      // Any other failure: the text field stays usable.
    }
  }

  const button = h("button", { class: "button button--primary", type: "submit" }, text.createParcel);
  const form = h(
    "form",
    {
      class: "form",
      onsubmit: async (event) => {
        event.preventDefault();
        const body = { locker: locker.value.trim(), recipient_phone: recipient.value.trim(), size: size.value };
        const signature = JSON.stringify(body);
        // The same details after an unknown outcome reuse the key, so the parcel is
        // not created twice.
        if (signature !== lastBody || !key) key = api.newIdempotencyKey();
        lastBody = signature;
        button.disabled = true;
        button.textContent = text.creating;
        show(feedback, null);
        try {
          const parcel = await api.createParcel(app.org, body, key);
          key = null;
          lastBody = "";
          if (app.token !== token) return;
          recipient.value = "";
          show(feedback, h("p", { class: "message message--ok", role: "status" }, s.createdText(parcel)));
          recipient.focus();
        } catch (error) {
          if (app.token !== token) return;
          if (error instanceof SessionEnded) return app.signedOut(text.sessionEnded);
          if (!(error instanceof NetworkError)) key = null; // a definite answer
          show(feedback, h("p", { class: "message message--error", role: "alert" }, s.createMessage(error)));
        } finally {
          if (app.token === token) {
            button.disabled = false;
            button.textContent = text.createParcel;
          }
        }
      },
    },
    h("label", { class: "label", for: "locker" }, text.lockerLabel),
    lockerBox,
    h("p", { class: "hint" }, text.lockerHelp),
    h("label", { class: "label", for: "recipient" }, text.recipientLabel),
    recipient,
    h("p", { class: "hint" }, text.recipientHelp),
    h("label", { class: "label", for: "size" }, text.sizeLabel),
    size,
    feedback,
    button,
  );

  show(app.root, h("a", { class: "back", href: "#/" }, text.backToParcels), h("h1", {}, text.newParcel), form);
  if (app.role === "admin") loadLockers();
}
