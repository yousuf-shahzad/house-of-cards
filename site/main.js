// Orchestrator-owned: component mounting + hash router.
//
// COMPONENTS (always on screen): components/NAME.js does
//   (window.components ||= {}).NAME = (el) => { el.innerHTML = `...`; };
//   mounted into <div id="NAME">. Styles scoped under #NAME, use CSS vars from style.css.
//
// PAGES: pages/NAME.js does
//   (window.pages ||= {}).NAME = (el) => { el.innerHTML = `...`; };
//   rendered into <div id="view"> when the hash is #/NAME. Scope styles under #view .NAME-page
//   (wrap your markup in <section class="NAME-page">). Re-rendered on every visit, so
//   keep state in localStorage if it should survive navigation.
//
// ROUTES: "#/" or any hash NOT starting with "#/" (e.g. "#features") = home
//   (hero + features). "#/about", "#/playground", "#/contact" = pages.
//
// EVENT: on every navigation, window dispatches
//   CustomEvent("routechange", { detail: { route: "home" | "about" | ... } }).
//   The fluid background (#fluid) is only visible on home; it should pause its
//   animation loop when route !== "home" and resume on home.
const PAGES = ["about", "playground", "contact"];

for (const name of ["header", "hero", "features", "footer", "fluid"]) {
  const el = document.getElementById(name);
  const render = window.components && window.components[name];
  if (render) render(el);
  else if (name !== "fluid") el.innerHTML = `<p class="placeholder">[${name}: not built yet]</p>`;
}

function routeFromHash() {
  const m = location.hash.match(/^#\/(\w+)/);
  return m && PAGES.includes(m[1]) ? m[1] : "home";
}

function navigate() {
  const route = routeFromHash();
  const home = route === "home";
  document.getElementById("home").hidden = !home;
  document.getElementById("fluid").hidden = !home;
  const view = document.getElementById("view");
  view.hidden = home;
  if (!home) {
    const render = window.pages && window.pages[route];
    view.innerHTML = "";
    if (render) render(view);
    else view.innerHTML = `<p class="placeholder">[${route}: not built yet]</p>`;
    window.scrollTo(0, 0);
  }
  document.querySelectorAll("#header nav a").forEach((a) => {
    const h = a.getAttribute("href");
    a.toggleAttribute("aria-current", (h === "#/" && home) || h === `#/${route}`);
  });
  window.dispatchEvent(new CustomEvent("routechange", { detail: { route } }));
}

window.addEventListener("hashchange", navigate);
navigate();
