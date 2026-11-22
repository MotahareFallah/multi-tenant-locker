import { h, show } from "../../js/dom.js";
import { ApiError, SessionEnded } from "../../js/errors.js";
import * as api from "./api.js";
import * as s from "./strings.js";
import { parcelsView } from "./parcels.js";

const { text } = s;

const failure = (body) => h("p", { class: "message message--error", role: "alert" }, body);

// The landing page: which organization and which role. The staff pages hang off
// this one.
export function homeView(app) {
  const token = app.token;

  async function load() {
    show(app.root, h("h1", {}, text.brand), h("p", { class: "hint" }, text.loading));
    try {
      const organization = await api.getOrganization(app.org);
      if (app.token !== token) return;
      app.role = organization.role;
      app.drawTop();
      document.title = `${organization.name} · ${text.brand}`;
      parcelsView(app);
    } catch (error) {
      if (app.token !== token) return;
      if (error instanceof SessionEnded) return app.signedOut(text.sessionEnded);
      const retryable = !(error instanceof ApiError && error.status === 404);
      show(
        app.root,
        h("h1", {}, text.brand),
        failure(s.organizationMessage(error)),
        retryable ? h("button", { class: "button", type: "button", onclick: load }, text.retry) : null,
      );
    }
  }

  load();
}
