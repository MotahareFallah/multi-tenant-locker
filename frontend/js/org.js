// Which organization this page is for. It comes from the `?org=` link and is kept
// for the rest of the tab's life. The value goes into API paths, so it is checked
// against a strict pattern first.
const ORG_KEY = "locker.org";
const ORG_PATTERN = /^[-a-zA-Z0-9_]{1,64}$/;

export function findOrg() {
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
