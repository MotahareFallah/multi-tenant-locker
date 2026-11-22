import * as api from "./api.js";
import { door, swingOpen } from "./door.js";
import { h, show } from "./dom.js";
import { ApiError, NetworkError, SessionEnded } from "./errors.js";
import * as s from "./strings.js";

const { text } = s;

const message = (kind, body, extra = {}) =>
  h("p", { class: `message message--${kind}`, role: kind === "error" ? "alert" : "status", ...extra }, body);

export function orgView(root) {
  show(root, h("h1", {}, text.orgTitle), h("p", {}, text.orgHelp));
}

export function signInView(app, notice) {
  const root = app.root;
  let phone = "";
  let timer = null;
  app.onLeave(() => clearInterval(timer));

  function phoneStep(error) {
    clearInterval(timer);
    const input = h("input", { class: "input", id: "phone", type: "tel", inputmode: "tel", autocomplete: "tel", required: true, value: phone });
    const button = h("button", { class: "button button--primary", type: "submit" }, text.sendCode);
    const form = h(
      "form",
      {
        class: "form",
        onsubmit: async (event) => {
          event.preventDefault();
          phone = input.value.trim();
          if (!phone) return;
          button.disabled = true;
          button.textContent = text.sending;
          try {
            await api.requestCode(phone);
            codeStep();
          } catch (e) {
            phoneStep(s.codeRequestMessage(e));
          }
        },
      },
      h("label", { class: "label", for: "phone" }, text.phoneLabel),
      input,
      h("p", { class: "hint" }, text.phoneHelp),
      button,
    );
    show(root, h("h1", {}, text.signInTitle), notice && !error ? message("info", notice) : null, error ? message("error", error) : null, form);
    input.focus();
  }

  function codeStep(error) {
    clearInterval(timer);
    const input = h("input", { class: "input input--code", id: "code", inputmode: "numeric", autocomplete: "one-time-code", maxlength: "6", required: true });
    const button = h("button", { class: "button button--primary", type: "submit" }, text.verify);
    const resend = h("button", { class: "link", type: "button", disabled: true }, s.resendIn(60));
    let left = 60;
    timer = setInterval(() => {
      left -= 1;
      if (left <= 0) {
        clearInterval(timer);
        resend.disabled = false;
        resend.textContent = text.resend;
      } else resend.textContent = s.resendIn(left);
    }, 1000);
    resend.addEventListener("click", async () => {
      resend.disabled = true;
      try {
        await api.requestCode(phone);
        codeStep();
      } catch (e) {
        codeStep(s.codeRequestMessage(e));
      }
    });
    const form = h(
      "form",
      {
        class: "form",
        onsubmit: async (event) => {
          event.preventDefault();
          button.disabled = true;
          button.textContent = text.verifying;
          try {
            await api.verifyCode(phone, input.value.trim());
            app.navigate("#/");
            app.render({ moved: true });
          } catch (e) {
            codeStep(s.verifyMessage(e));
          }
        },
      },
      h("label", { class: "label", for: "code" }, text.codeLabel),
      input,
      button,
    );
    show(
      root,
      h("h1", {}, text.signInTitle),
      error ? message("error", error) : message("info", s.codeSent(phone)),
      form,
      h("div", { class: "row" }, resend, h("button", { class: "link", type: "button", onclick: () => phoneStep() }, text.otherNumber)),
    );
    input.focus();
  }

  phoneStep();
}

function parcelRow(app, parcel) {
  const st = s.statusOf(parcel.status);
  return h(
    "li",
    {},
    h(
      "a",
      { class: `parcel parcel--${st.tone}`, href: `#/parcels/${encodeURIComponent(parcel.tracking_code)}` },
      door({ number: parcel.compartment, size: parcel.size, tone: st.tone }),
      h(
        "span",
        { class: "parcel__body" },
        h("span", { class: "parcel__code" }, parcel.tracking_code),
        h("span", { class: `badge badge--${st.tone}` }, st.label),
        h("span", { class: "parcel__where" }, s.whereText(parcel)),
      ),
    ),
  );
}

export function listView(app) {
  const root = app.root;
  const token = app.token;
  const parcels = [];
  let page = 1;
  let next = null;

  function draw(extra) {
    if (app.token !== token) return;
    const ready = parcels.filter((p) => p.status === "READY_FOR_PICKUP");
    const others = parcels.filter((p) => p.status !== "READY_FOR_PICKUP").sort((a, b) => s.statusOf(a.status).rank - s.statusOf(b.status).rank);
    const group = (title, rows) =>
      rows.length ? h("section", { class: "group" }, h("h2", {}, title), h("ul", { class: "parcels" }, rows.map((p) => parcelRow(app, p)))) : null;
    show(
      root,
      h("h1", {}, text.parcelsTitle),
      parcels.length === 0 && !extra ? message("info", text.empty) : null,
      group(text.readyGroup, ready),
      group(text.otherGroup, others),
      next ? h("button", { class: "button", type: "button", onclick: () => load(page + 1) }, text.showMore) : null,
      extra ?? null,
    );
  }

  async function load(n) {
    try {
      const data = await api.listParcels(app.org, n);
      if (app.token !== token) return;
      page = n;
      parcels.push(...(data.results ?? []));
      next = data.next;
      draw();
    } catch (error) {
      if (app.token !== token) return;
      if (error instanceof SessionEnded) return app.signedOut(text.sessionEnded);
      draw(h("div", {}, message("error", s.listMessage(error)), h("button", { class: "button", type: "button", onclick: () => load(n) }, text.retry)));
    }
  }

  show(root, h("h1", {}, text.parcelsTitle), h("p", { class: "hint" }, text.loading));
  load(1);
}

export function detailView(app, trackingCode) {
  const root = app.root;
  const token = app.token;
  const back = h("a", { class: "back", href: "#/" }, text.back);

  async function load() {
    try {
      render(await api.getParcel(app.org, trackingCode));
    } catch (error) {
      if (app.token !== token) return;
      if (error instanceof SessionEnded) return app.signedOut(text.sessionEnded);
      show(root, back, message("error", s.parcelMessage(error)), h("button", { class: "button", type: "button", onclick: load }, text.retry));
    }
  }

  function facts(parcel) {
    const rows = [
      [text.trackingCode, parcel.tracking_code],
      [text.locker, parcel.locker ?? "–"],
      [text.compartment, parcel.compartment ?? "–"],
      [text.size, parcel.size ? String(parcel.size).toLowerCase() : "–"],
      [text.expires, s.formatWhen(parcel.expires_at) || "–"],
      [text.added, s.formatWhen(parcel.created_at) || "–"],
    ];
    return h("dl", { class: "facts" }, rows.map(([k, v]) => [h("dt", {}, k), h("dd", {}, v)]));
  }

  function render(parcel, { note, opened = false } = {}) {
    if (app.token !== token) return;
    const st = s.statusOf(parcel.status);
    const stage = door({ number: parcel.compartment, size: parcel.size, tone: st.tone, scale: "lg" });
    if (opened) stage.classList.add("is-open");
    const section = h(
      "section",
      { class: "detail" },
      stage,
      h("h1", {}, parcel.tracking_code),
      h("p", { class: `badge badge--${st.tone}` }, st.label),
      h("p", {}, s.whereText(parcel)),
    );
    const form = parcel.status === "READY_FOR_PICKUP" ? pickupForm(parcel, stage) : h("p", { class: "hint" }, parcel.status === "DELIVERED" || parcel.status === "EXPIRED" ? text.notReadyDone : text.notReady);
    show(root, back, section, note ?? null, facts(parcel), form);
  }

  function pickupForm(parcel, stage) {
    let key = null;
    let lastCode = "";
    const feedback = h("div", { class: "feedback" });
    const input = h("input", { class: "input input--code", id: "pickup", autocomplete: "off", autocapitalize: "characters", spellcheck: "false", maxlength: "32", required: true });
    const button = h("button", { class: "button button--go", type: "submit" }, text.openDoor);
    const setFeedback = (node) => show(feedback, node ?? null);
    const form = h(
      "form",
      {
        class: "form",
        onsubmit: async (event) => {
          event.preventDefault();
          const code = input.value.trim();
          if (!code) return;
          // Same code again after an unknown outcome: same key, so the server
          // replays the first answer instead of opening the door twice.
          if (code !== lastCode || !key) key = api.newIdempotencyKey();
          lastCode = code;
          button.disabled = true;
          button.textContent = text.opening;
          setFeedback(null);
          try {
            const updated = await api.pickup(app.org, parcel.tracking_code, code, key);
            key = null;
            if (app.token !== token) return;
            render(updated ?? { ...parcel, status: "DELIVERED" }, { note: message("ok", s.doorIsOpen((updated ?? parcel).compartment)) });
            swingOpen(root.querySelector(".door-stage"));
          } catch (error) {
            if (app.token !== token) return;
            if (error instanceof SessionEnded) return app.signedOut(text.sessionEnded);
            if (error instanceof NetworkError) {
              // Outcome unknown: keep the key.
            } else {
              key = null;
            }
            if (error instanceof ApiError && error.body?.parcel) {
              return render(error.body.parcel, { note: message("error", s.pickupMessage(error)) });
            }
            if (error instanceof ApiError && error.status === 409) {
              await load();
              root.insertBefore(message("error", s.pickupMessage(error)), root.querySelector(".facts"));
              return;
            }
            setFeedback(message("error", s.pickupMessage(error)));
            button.textContent = text.openDoor;
            if (error instanceof ApiError && error.code === "pickup_blocked") return;
            button.disabled = false;
            if (error instanceof ApiError && error.code === "wrong_pickup_code") input.value = "";
            input.focus();
          }
        },
      },
      h("h2", {}, text.pickupTitle),
      h("label", { class: "label", for: "pickup" }, text.pickupLabel),
      input,
      h("p", { class: "hint" }, s.pickupHelp),
      feedback,
      button,
    );
    return form;
  }

  show(root, back, h("p", { class: "hint" }, text.loading));
  load();
}
