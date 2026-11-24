import { h, show } from "../../js/dom.js";
import { NetworkError, SessionEnded } from "../../js/errors.js";
import * as api from "./api.js";
import * as s from "./strings.js";

const { text } = s;

const message = (kind, body) =>
  h("p", { class: `message message--${kind}`, role: kind === "error" ? "alert" : "status" }, body);

// The organization's members. Only admins may see this; the server enforces it.
export function membersView(app) {
  app.wide(true);
  const token = app.token;
  let page = 1;
  let rows = [];
  let total = 0;
  let next = null;

  const listBox = h("div", {});
  const notice = h("div", { class: "feedback" });

  // One PATCH per click. The row is replaced with what the server answers.
  async function change(member, patch, button, done) {
    const label = button.textContent;
    button.disabled = true;
    button.textContent = text.working;
    show(notice, null);
    try {
      const updated = await api.updateMember(app.org, member.id, patch);
      if (app.token !== token) return;
      rows = rows.map((item) => (item.id === updated.id ? updated : item));
      draw();
      show(notice, message("ok", done(updated)));
    } catch (error) {
      if (app.token !== token) return;
      if (error instanceof SessionEnded) return app.signedOut(text.sessionEnded);
      show(notice, message("error", s.updateMemberMessage(error)));
      button.disabled = false;
      button.textContent = label;
    }
  }

  function actions(member) {
    const isAdmin = member.role === "admin";
    const roleButton = h("button", { class: "link", type: "button" }, isAdmin ? text.makeOperator : text.makeAdmin);
    roleButton.addEventListener("click", () =>
      change(member, { role: isAdmin ? "operator" : "admin" }, roleButton, s.roleChangedText),
    );
    const activeButton = h("button", { class: "link", type: "button" }, member.is_active ? text.deactivate : text.reactivate);
    activeButton.addEventListener("click", () =>
      change(member, { is_active: !member.is_active }, activeButton, s.activeChangedText),
    );
    return h("div", { class: "row-actions" }, roleButton, activeButton);
  }

  function row(member) {
    return h(
      "tr",
      {},
      h("td", {}, member.phone_number),
      h("td", {}, member.full_name || "–"),
      h("td", {}, s.roleText(member.role)),
      h(
        "td",
        {},
        h("span", { class: `badge badge--${member.is_active ? "ready" : "done"}` }, member.is_active ? text.active : text.inactive),
      ),
      h("td", {}, s.formatWhen(member.created_at)),
      h("td", {}, actions(member)),
    );
  }

  function draw(extra) {
    if (app.token !== token) return;
    show(
      listBox,
      rows.length ? h("p", { class: "hint" }, s.memberCountText(total)) : null,
      rows.length === 0 && !extra ? h("p", { class: "message message--info" }, text.emptyMembers) : null,
      rows.length
        ? h(
            "div",
            { class: "table-wrap" },
            h(
              "table",
              { class: "table", "aria-label": text.membersTitle },
              h("thead", {}, h("tr", {}, text.memberColumns.map((name) => h("th", { scope: "col" }, name)))),
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
      const data = await api.listMembers(app.org, n);
      if (app.token !== token) return;
      // A paginated answer, or a plain list if the API is ever not paginated.
      const items = Array.isArray(data) ? data : (data.results ?? []);
      page = n;
      total = Array.isArray(data) ? data.length : data.count;
      rows = rows.concat(items);
      next = Array.isArray(data) ? null : data.next;
      draw();
    } catch (error) {
      if (app.token !== token) return;
      if (error instanceof SessionEnded) return app.signedOut(text.sessionEnded);
      const message = s.membersMessage(error);
      draw(
        h(
          "div",
          {},
          h("p", { class: "message message--error", role: "alert" }, message),
          message === text.adminsOnly ? null : h("button", { class: "button", type: "button", onclick: () => load(n) }, text.retry),
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
    const phone = h("input", { class: "input", id: "member-phone", type: "tel", inputmode: "tel", autocomplete: "off", required: true });
    const role = h("select", { class: "select", id: "member-role" }, s.memberRoleOptions.map(([value, label]) => h("option", { value }, label)));
    const button = h("button", { class: "button button--primary", type: "submit" }, text.addMember);
    return h(
      "form",
      {
        class: "form",
        onsubmit: async (event) => {
          event.preventDefault();
          button.disabled = true;
          button.textContent = text.adding;
          show(feedback, null);
          try {
            const member = await api.addMember(app.org, { phone_number: phone.value.trim(), role: role.value });
            if (app.token !== token) return;
            phone.value = "";
            show(feedback, h("p", { class: "message message--ok", role: "status" }, s.addedText(member)));
            reload();
          } catch (error) {
            if (app.token !== token) return;
            if (error instanceof SessionEnded) return app.signedOut(text.sessionEnded);
            show(feedback, h("p", { class: "message message--error", role: "alert" }, s.addMemberMessage(error)));
          } finally {
            if (app.token === token) {
              button.disabled = false;
              button.textContent = text.addMember;
            }
          }
        },
      },
      h("h2", {}, text.addMemberTitle),
      h("label", { class: "label", for: "member-phone" }, text.memberPhoneLabel),
      phone,
      h("label", { class: "label", for: "member-role" }, text.memberRoleLabel),
      role,
      feedback,
      button,
    );
  }

  show(app.root, h("h1", {}, text.membersTitle), app.role === "admin" ? addForm() : null, notice, listBox);
  reload();
}
