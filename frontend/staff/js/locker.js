import { h, show } from "../../js/dom.js";
import { ApiError, SessionEnded } from "../../js/errors.js";
import * as api from "./api.js";
import * as s from "./strings.js";

const { text } = s;

// One locker with its compartments. Only admins may see this; the server enforces it.
export function lockerView(app, code) {
  app.wide(true);
  const token = app.token;
  const box = h("div", {});

  function draw(locker) {
    if (app.token !== token) return;
    const compartments = locker.compartments ?? [];
    show(
      box,
      h(
        "p",
        {},
        h("span", { class: `badge badge--${locker.is_active ? "ready" : "done"}` }, locker.is_active ? text.active : text.inactive),
      ),
      h("p", {}, `${text.lockerNameLabel}: ${locker.name || "–"}`),
      h("p", {}, `${text.lockerAddressLabel}: ${locker.address || "–"}`),
      h("h2", {}, text.compartmentsTitle),
      compartments.length === 0 ? h("p", { class: "message message--info" }, text.emptyCompartments) : null,
      compartments.length
        ? h("p", { class: "hint" }, s.compartmentCountText(compartments.length))
        : null,
      compartments.length
        ? h(
            "div",
            { class: "table-wrap" },
            h(
              "table",
              { class: "table", "aria-label": text.compartmentsTitle },
              h("thead", {}, h("tr", {}, text.compartmentColumns.map((name) => h("th", { scope: "col" }, name)))),
              h(
                "tbody",
                {},
                compartments.map((compartment) =>
                  h(
                    "tr",
                    {},
                    h("td", {}, compartment.number),
                    h("td", {}, s.sizeText(compartment.size)),
                    h(
                      "td",
                      {},
                      h("span", { class: `badge badge--${compartment.is_active ? "ready" : "done"}` }, compartment.is_active ? text.active : text.inactive),
                    ),
                  ),
                ),
              ),
            ),
          )
        : null,
    );
  }

  async function load() {
    show(box, h("p", { class: "hint" }, text.loading));
    try {
      const locker = await api.getLocker(app.org, code);
      if (app.token !== token) return;
      draw(locker);
    } catch (error) {
      if (app.token !== token) return;
      if (error instanceof SessionEnded) return app.signedOut(text.sessionEnded);
      const retryable = !(error instanceof ApiError && (error.status === 403 || error.status === 404));
      show(
        box,
        h("p", { class: "message message--error", role: "alert" }, s.lockerMessage(error)),
        retryable ? h("button", { class: "button", type: "button", onclick: load }, text.retry) : null,
      );
    }
  }

  show(app.root, h("a", { class: "link", href: "#/lockers" }, text.backToLockers), h("h1", {}, code), box);
  load();
}
