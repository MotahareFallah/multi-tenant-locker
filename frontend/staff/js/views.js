import { h, show } from "../../js/dom.js";
import { ApiError, SessionEnded } from "../../js/errors.js";
import * as api from "./api.js";
import * as s from "./strings.js";
import { membersView } from "./members.js";
import { newParcelView } from "./new-parcel.js";
import { parcelView } from "./parcel.js";
import { parcelsView } from "./parcels.js";

const { text } = s;

const failure = (body) => h("p", { class: "message message--error", role: "alert" }, body);

// The landing page: which organization and which role. The staff pages hang off
// this one.
export function homeView(app) {
  const token = app.token;

  async function load() {
    if (!app.organization) show(app.root, h("h1", {}, text.brand), h("p", { class: "hint" }, text.loading));
    try {
      // Asked once per sign-in, not on every page. The server still checks the
      // membership on every request.
      const organization = app.organization ?? (await api.getOrganization(app.org));
      app.organization = organization;
      if (app.token !== token) return;
      app.role = organization.role;
      app.drawTop();
      document.title = `${organization.name} · ${text.brand}`;
      const parcel = /^#\/parcels\/([^/]+)$/.exec(location.hash);
      if (location.hash === "#/new") newParcelView(app);
      else if (location.hash === "#/members") membersView(app);
      else if (parcel) parcelView(app, decodeURIComponent(parcel[1]));
      else parcelsView(app);
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
