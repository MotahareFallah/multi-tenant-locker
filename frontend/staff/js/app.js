import { h, show } from "../../js/dom.js";
import { findOrg } from "../../js/org.js";
import { orgView, signInView } from "../../js/views.js";
import * as api from "./api.js";
import * as s from "./strings.js";
import { homeView } from "./views.js";

const { text } = s;

const cleanups = [];
const app = {
  org: findOrg(),
  role: null,
  root: document.getElementById("view"),
  token: Symbol("view"),
  onLeave: (fn) => cleanups.push(fn),
  navigate: (hash) => {
    history.replaceState(null, "", location.pathname + location.search + hash);
  },
  signedOut: (notice) => {
    app.role = null;
    app.navigate("#/");
    render({ notice });
  },
  wide: (on) => document.querySelector(".app").classList.toggle("app--wide", on),
  drawTop: () => drawTop(),
  render: (options) => render(options),
};

function drawTop() {
  show(
    document.getElementById("top"),
    h("a", { class: "brand", href: "#/" }, text.brand),
    app.org ? h("span", { class: "plate" }, app.org) : null,
    app.role ? h("span", { class: "plate" }, s.roleText(app.role)) : null,
    api.hasSession()
      ? h(
          "button",
          {
            class: "link",
            type: "button",
            onclick: async () => {
              await api.signOut();
              app.signedOut(null);
            },
          },
          text.signOut,
        )
      : null,
  );
  show(document.getElementById("foot"), h("span", {}, text.footer));
}

function render({ moved = false, notice = null } = {}) {
  while (cleanups.length) cleanups.pop()();
  app.token = Symbol("view");
  app.wide(false);
  drawTop();
  if (!app.org) {
    orgView(app.root);
  } else if (!api.hasSession()) {
    signInView(app, notice);
  } else {
    homeView(app);
  }
  document.title = text.brand;
  if (moved) app.root.focus({ preventScroll: true });
}

window.addEventListener("hashchange", () => render({ moved: true }));
render();
