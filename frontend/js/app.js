import * as api from "./api.js";
import { h, show } from "./dom.js";
import * as s from "./strings.js";
import { detailView, listView, orgView, signInView } from "./views.js";

const ORG_KEY = "locker.org";
const ORG_PATTERN = /^[-a-zA-Z0-9_]{1,64}$/;

function findOrg() {
  const fromUrl = new URLSearchParams(location.search).get("org");
  try {
    if (fromUrl && ORG_PATTERN.test(fromUrl)) {
      sessionStorage.setItem(ORG_KEY, fromUrl);
      return fromUrl;
    }
    const kept = sessionStorage.getItem(ORG_KEY);
    return kept && ORG_PATTERN.test(kept) ? kept : null;
  } catch {
    return fromUrl && ORG_PATTERN.test(fromUrl) ? fromUrl : null;
  }
}

const cleanups = [];
const app = {
  org: findOrg(),
  root: document.getElementById("view"),
  token: Symbol("view"),
  onLeave: (fn) => cleanups.push(fn),
  navigate: (hash) => {
    history.replaceState(null, "", location.pathname + location.search + hash);
  },
  signedOut: (notice) => {
    app.navigate("#/");
    drawTop();
    render({ notice });
  },
  render: (options) => render(options),
};

function drawTop() {
  const out = api.hasSession();
  show(
    document.getElementById("top"),
    h("a", { class: "brand", href: "#/" }, s.text.brand),
    app.org ? h("span", { class: "plate" }, app.org) : null,
    out
      ? h("button", { class: "link", type: "button", onclick: async () => { await api.signOut(); app.signedOut(null); } }, s.text.signOut)
      : null,
  );
  show(document.getElementById("foot"), h("span", {}, s.text.footer));
}

function render({ moved = false, notice = null } = {}) {
  while (cleanups.length) cleanups.pop()();
  app.token = Symbol("view");
  drawTop();
  let title = s.text.brand;
  if (!app.org) {
    orgView(app.root);
  } else if (!api.hasSession()) {
    title = `${s.text.signInTitle} · ${s.text.brand}`;
    signInView(app, notice);
  } else {
    const match = /^#\/parcels\/([^/]+)$/.exec(location.hash);
    if (match) {
      const code = decodeURIComponent(match[1]);
      title = `${code} · ${s.text.brand}`;
      detailView(app, code);
    } else {
      title = `${s.text.parcelsTitle} · ${s.text.brand}`;
      listView(app);
    }
  }
  document.title = title;
  if (moved) app.root.focus({ preventScroll: true });
}

window.addEventListener("hashchange", () => render({ moved: true }));
render();
