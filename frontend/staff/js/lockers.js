import { h, show } from "../../js/dom.js";
import { SessionEnded } from "../../js/errors.js";
import * as api from "./api.js";
import * as s from "./strings.js";

const { text } = s;

// The organization's lockers. Only admins may see this; the server enforces it.
export function lockersView(app) {
  app.wide(true);
  const token = app.token;
  let page = 1;
  let rows = [];
  let total = 0;
  let next = null;

  const listBox = h("div", {});

  function row(locker) {
    return h(
      "tr",
      {},
      h("td", { class: "code" }, h("a", { class: "link", href: `#/lockers/${encodeURIComponent(locker.code)}` }, locker.code)),
      h("td", {}, locker.name || "–"),
      h("td", {}, locker.address || "–"),
      h(
        "td",
        {},
        h("span", { class: `badge badge--${locker.is_active ? "ready" : "done"}` }, locker.is_active ? text.active : text.inactive),
      ),
    );
  }

  function draw(extra) {
    if (app.token !== token) return;
    show(
      listBox,
      rows.length ? h("p", { class: "hint" }, s.lockerCountText(total)) : null,
      rows.length === 0 && !extra ? h("p", { class: "message message--info" }, text.emptyLockers) : null,
      rows.length
        ? h(
            "div",
            { class: "table-wrap" },
            h(
              "table",
              { class: "table", "aria-label": text.lockersTitle },
              h("thead", {}, h("tr", {}, text.lockerColumns.map((name) => h("th", { scope: "col" }, name)))),
              h("tbody", {}, rows.map(row)),
            ),
          )
        : null,
      next ? h("button", { class: "button", type: "button", onclick: () => load(page + 1) }, text.showMore) : null,
      extra ?? null,
    );
  }

  async function load(n) {
    try {
      const data = await api.listLockers(app.org, n);
      if (app.token !== token) return;
      const items = Array.isArray(data) ? data : (data.results ?? []);
      page = n;
      total = Array.isArray(data) ? data.length : data.count;
      rows = rows.concat(items);
      next = Array.isArray(data) ? null : data.next;
      draw();
    } catch (error) {
      if (app.token !== token) return;
      if (error instanceof SessionEnded) return app.signedOut(text.sessionEnded);
      const reason = s.lockersMessage(error);
      draw(
        h(
          "div",
          {},
          h("p", { class: "message message--error", role: "alert" }, reason),
          reason === text.adminsOnly ? null : h("button", { class: "button", type: "button", onclick: () => load(n) }, text.retry),
        ),
      );
    }
  }

  function reload() {
    rows = [];
    next = null;
    show(listBox, h("p", { class: "hint" }, text.loading));
    load(1);
  }

  function addForm() {
    const feedback = h("div", { class: "feedback" });
    const code = h("input", { class: "input", id: "locker-code", type: "text", autocomplete: "off", autocapitalize: "off", spellcheck: "false", required: true });
    const name = h("input", { class: "input", id: "locker-name", type: "text", autocomplete: "off" });
    const address = h("input", { class: "input", id: "locker-address", type: "text", autocomplete: "off" });
    const button = h("button", { class: "button button--primary", type: "submit" }, text.addLocker);
    return h(
      "form",
      {
        class: "form",
        onsubmit: async (event) => {
          event.preventDefault();
          button.disabled = true;
          button.textContent = text.adding;
          show(feedback, null);
          // Empty optional fields are left out, so the server's own defaults apply.
          const body = { code: code.value.trim() };
          if (name.value.trim()) body.name = name.value.trim();
          if (address.value.trim()) body.address = address.value.trim();
          try {
            const locker = await api.createLocker(app.org, body);
            if (app.token !== token) return;
            code.value = "";
            name.value = "";
            address.value = "";
            show(feedback, h("p", { class: "message message--ok", role: "status" }, s.lockerAddedText(locker)));
            reload();
          } catch (error) {
            if (app.token !== token) return;
            if (error instanceof SessionEnded) return app.signedOut(text.sessionEnded);
            show(feedback, h("p", { class: "message message--error", role: "alert" }, s.addLockerMessage(error)));
          } finally {
            if (app.token === token) {
              button.disabled = false;
              button.textContent = text.addLocker;
            }
          }
        },
      },
      h("h2", {}, text.addLockerTitle),
      h("label", { class: "label", for: "locker-code" }, text.lockerCodeLabel),
      code,
      h("p", { class: "hint" }, text.lockerCodeHelp),
      h("label", { class: "label", for: "locker-name" }, text.lockerNameLabel),
      name,
      h("label", { class: "label", for: "locker-address" }, text.lockerAddressLabel),
      address,
      feedback,
      button,
    );
  }

  show(app.root, h("h1", {}, text.lockersTitle), app.role === "admin" ? addForm() : null, listBox);
  reload();
}
