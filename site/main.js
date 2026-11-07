// Orchestrator-owned. Mounts every registered component into <div id="NAME">.
// Contract: each components/NAME.js does
//   (window.components ||= {}).NAME = (el) => { el.innerHTML = `...`; };
// Component styles go in the component's own <style> inside its innerHTML,
// scoped under #NAME. Use the CSS variables from style.css.
for (const name of ["header", "hero", "features", "footer"]) {
  const el = document.getElementById(name);
  const render = window.components && window.components[name];
  if (render) render(el);
  else el.innerHTML = `<p class="placeholder">[${name}: not built yet]</p>`;
}
