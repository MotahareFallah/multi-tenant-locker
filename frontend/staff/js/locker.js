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

  function addForm() {
    const feedback = h("div", { class: "feedback" });
    const number = h("input", { class: "input", id: "compartment-number", type: "number", min: "1", step: "1", inputmode: "numeric", autocomplete: "off", required: true });
    const size = h("select", { class: "select", id: "compartment-size" }, s.sizeOptions.map(([value, label]) => h("option", { value }, label)));
    const button = h("button", { class: "button button--primary", type: "submit" }, text.addCompartment);
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
            const compartment = await api.addCompartment(app.org, code, { number: Number(number.value), size: size.value });
            if (app.token !== token) return;
            number.value = "";
            show(feedback, h("p", { class: "message message--ok", role: "status" }, s.compartmentAddedText(compartment)));
            load();
          } catch (error) {
            if (app.token !== token) return;
            if (error instanceof SessionEnded) return app.signedOut(text.sessionEnded);
            show(feedback, h("p", { class: "message message--error", role: "alert" }, s.addCompartmentMessage(error)));
          } finally {
            if (app.token === token) {
              button.disabled = false;
              button.textContent = text.addCompartment;
            }
          }
        },
      },
      h("h2", {}, text.addCompartmentTitle),
      h("label", { class: "label", for: "compartment-number" }, text.compartmentNumberLabel),
      number,
      h("p", { class: "hint" }, text.compartmentNumberHelp),
      h("label", { class: "label", for: "compartment-size" }, text.sizeLabel),
      size,
      feedback,
      button,
    );
  }

  show(app.root, h("a", { class: "link", href: "#/lockers" }, text.backToLockers), h("h1", {}, code), box, addForm());
  load();
}
