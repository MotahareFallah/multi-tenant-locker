// A tiny element builder. Text is always added as a text node, never parsed as
// HTML, so nothing that comes from the API can inject markup.
//
// Absent children (null, undefined, false) are skipped. Note that the DOM's own
// replaceChildren/append turn null into the text "null", so pass them through h().
export function h(tag, attrs = {}, ...children) {
  const element = document.createElement(tag);
  for (const [name, value] of Object.entries(attrs ?? {})) {
    if (value === false || value == null) continue;
    if (name.startsWith("on") && typeof value === "function") {
      element.addEventListener(name.slice(2), value);
    } else if (name === "class") {
      element.className = value;
    } else if (value === true) {
      element.setAttribute(name, "");
    } else {
      element.setAttribute(name, value);
    }
  }
  for (const child of children.flat(Infinity)) {
    if (child == null || child === false) continue;
    element.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return element;
}

// Replace what is inside `parent`, skipping absent parts.
export function show(parent, ...children) {
  parent.replaceChildren(...children.flat(Infinity).filter((child) => child != null && child !== false));
}
