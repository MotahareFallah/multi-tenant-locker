import { h } from "./dom.js";

// A locker door. It carries information: the plate is the compartment number, the
// height follows the compartment size, and the light shows the status tone. The
// door is decorative for screen readers; the same facts are written out nearby.
export function door({ number, size, tone = "wait", scale = "sm" }) {
  return h(
    "div",
    {
      class: `door-stage door-stage--${scale}`,
      "data-size": String(size ?? "medium").toLowerCase(),
      "data-tone": tone,
      "aria-hidden": "true",
    },
    h("div", { class: "door-bay" }),
    h(
      "div",
      { class: "door" },
      h("span", { class: "door__light" }),
      h("span", { class: "door__number" }, number ?? "–"),
      h("span", { class: "door__handle" }),
    ),
  );
}

// Swing the door open. Called after the server accepted the pickup code.
export function swingOpen(stage) {
  requestAnimationFrame(() => requestAnimationFrame(() => stage.classList.add("is-open")));
}
