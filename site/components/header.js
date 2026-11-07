// header: site title + nav links with mobile menu toggle. Owner: Yousuf's Claude.
(window.components ||= {}).header = (el) => {
  el.innerHTML = `
    <style>
      #header .bar { display: flex; align-items: center; justify-content: space-between;
        flex-wrap: wrap; gap: 12px; padding: 14px 20px; border-bottom: 1px solid var(--surface); }
      #header .title { font-weight: 700; font-size: 1.25rem; text-decoration: none; color: var(--text); }
      #header nav { display: flex; gap: 16px; }
      #header nav a { text-decoration: none; color: var(--text); }
      #header nav a:hover, #header nav a[aria-current] { color: var(--accent); }
      #header .menu { display: none; background: none; border: 1px solid var(--muted); color: var(--text);
        border-radius: 8px; padding: 6px 10px; font-size: 1rem; cursor: pointer; }
      @media (max-width: 600px) {
        #header .menu { display: inline-block; }
        #header nav { display: none; flex-direction: column; width: 100%; gap: 10px; }
        #header nav[data-open="true"] { display: flex; }
      }
    </style>
    <div class="bar">
      <a class="title" href="#/">Hackathon Test Site</a>
      <button class="menu" type="button" aria-expanded="false" aria-controls="header-nav" aria-label="Toggle menu">&#9776;</button>
      <nav id="header-nav" aria-label="Main">
        <a href="#/">Home</a>
        <a href="#/about">About</a>
        <a href="#/playground">Playground</a>
        <a href="#/contact">Contact</a>
      </nav>
    </div>`;
  const btn = el.querySelector(".menu"), nav = el.querySelector("nav");
  const setOpen = (o) => { nav.dataset.open = String(o); btn.setAttribute("aria-expanded", String(o)); };
  btn.addEventListener("click", () => setOpen(nav.dataset.open !== "true"));
  nav.addEventListener("click", (e) => { if (e.target.closest("a")) setOpen(false); });
};
