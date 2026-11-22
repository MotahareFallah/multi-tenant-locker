import { h, show } from "../../js/dom.js";
import { SessionEnded } from "../../js/errors.js";
import * as api from "./api.js";
import * as s from "./strings.js";

const { text } = s;

// The parcel list: newest first, filtered by status, more rows on request.
export function parcelsView(app) {
  app.wide(true);
  const token = app.token;
  let status = "";
  let page = 1;
  let rows = [];
  let total = 0;
  let next = null;
  let attempt = 0;

  const listBox = h("div", {});
  const select = h(
    "select",
    {
      class: "select",
      id: "status",
      onchange: () => {
        status = select.value;
        reload();
      },
    },
    h("option", { value: "" }, text.allStatuses),
    s.statusOptions.map(([value, label]) => h("option", { value }, label)),
  );

  function row(parcel) {
    const st = s.statusOf(parcel.status);
    return h(
      "tr",
      {},
      h("td", {}, h("a", { class: "code", href: `#/parcels/${encodeURIComponent(parcel.tracking_code)}` }, parcel.tracking_code)),
      h("td", {}, parcel.recipient_phone),
      h("td", {}, h("span", { class: `badge badge--${st.tone}` }, st.label)),
      h("td", {}, s.whereText(parcel)),
      h("td", {}, String(parcel.size).toLowerCase()),
      h("td", {}, s.formatWhen(parcel.expires_at)),
    );
  }

  function draw(extra) {
    if (app.token !== token) return;
    const table = rows.length
      ? h(
          "div",
          { class: "table-wrap" },
          h(
            "table",
            { class: "table", "aria-label": text.parcelsTitle },
            h("thead", {}, h("tr", {}, text.columns.map((name) => h("th", { scope: "col" }, name)))),
            h("tbody", {}, rows.map(row)),
          ),
        )
      : null;
    show(
      listBox,
      rows.length ? h("p", { class: "hint" }, s.countText(total)) : null,
      rows.length === 0 && !extra ? h("p", { class: "message message--info" }, status ? text.emptyFiltered : text.empty) : null,
      table,
      next ? h("button", { class: "button", type: "button", onclick: () => load(page + 1, false) }, text.showMore) : null,
      extra ?? null,
    );
  }

  async function load(n, replace) {
    const mine = ++attempt;
    try {
      const data = await api.listParcels(app.org, { status, page: n });
      if (app.token !== token || mine !== attempt) return;
      page = n;
      total = data.count;
      rows = replace ? data.results : rows.concat(data.results);
      next = data.next;
      draw();
    } catch (error) {
      if (app.token !== token || mine !== attempt) return;
      if (error instanceof SessionEnded) return app.signedOut(text.sessionEnded);
      draw(
        h(
          "div",
          {},
          h("p", { class: "message message--error", role: "alert" }, s.listMessage(error)),
          h("button", { class: "button", type: "button", onclick: () => load(n, replace) }, text.retry),
        ),
      );
    }
  }

  function reload() {
    rows = [];
    next = null;
    show(listBox, h("p", { class: "hint" }, text.loading));
    load(1, true);
  }

  show(
    app.root,
    h("h1", {}, text.parcelsTitle),
    h(
      "div",
      { class: "toolbar" },
      h("label", { class: "label", for: "status" }, text.statusFilter),
      select,
      h("a", { class: "button button--primary", href: "#/new" }, text.newParcel),
    ),
    listBox,
  );
  reload();
}
