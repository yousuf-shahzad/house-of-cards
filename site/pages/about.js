// about page: one expandable card per agent. Owner: Yousuf's Claude.
(window.pages ||= {}).about = (el) => {
  const agents = [
    { name: "Gawyn's Claude", role: "Orchestrator", bio: "Owns index.html, main.js, style.css and the router, and integrates everyone's work." },
    { name: "Yousuf's Claude", role: "Header & About", bio: "Built the header navigation and this team page. Acts as team lead on the board." },
    { name: "Yousuf's Codex", role: "Hero & Fluid", bio: "Builds the hero section and the interactive fluid simulation behind the home screen." },
    { name: "Kendrick's Claude", role: "Features & Playground", bio: "Built the feature cards and the interactive playground widgets." },
    { name: "Bekarys's Claude", role: "Footer & Contact", bio: "Built the footer credits and the contact form with live validation." },
  ];
  const esc = (s) => s.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  el.innerHTML = `
    <style>
      #view .about-page h1 { margin: 0 0 .25rem; }
      #view .about-page .lede { color: var(--muted); margin: 0 0 1.25rem; }
      #view .about-page .card { background: var(--surface); border-radius: var(--radius); margin-bottom: .75rem; overflow: hidden; }
      #view .about-page .card button { all: unset; box-sizing: border-box; display: flex; width: 100%; align-items: center;
        justify-content: space-between; gap: 1rem; padding: 1rem 1.25rem; cursor: pointer; color: var(--text); }
      #view .about-page .card button:focus-visible { outline: 2px solid var(--accent); outline-offset: -2px; }
      #view .about-page .name { font-weight: 700; }
      #view .about-page .role { color: var(--accent); font-size: .875rem; }
      #view .about-page .chev { transition: transform .2s; color: var(--muted); }
      #view .about-page .card[data-open="true"] .chev { transform: rotate(90deg); }
      #view .about-page .body { display: none; padding: 0 1.25rem 1rem; color: var(--muted); }
      #view .about-page .card[data-open="true"] .body { display: block; }
    </style>
    <section class="about-page">
      <h1>About the team</h1>
      <p class="lede">Five agents, one site. Click a card to read more.</p>
      ${agents.map((a, i) => `
        <div class="card" data-open="false">
          <button type="button" aria-expanded="false" aria-controls="about-body-${i}">
            <span><span class="name">${esc(a.name)}</span><br><span class="role">${esc(a.role)}</span></span>
            <span class="chev" aria-hidden="true">&#9656;</span>
          </button>
          <div class="body" id="about-body-${i}">${esc(a.bio)}</div>
        </div>`).join("")}
    </section>`;
  el.querySelectorAll(".about-page .card button").forEach((btn) => {
    btn.addEventListener("click", () => {
      const card = btn.closest(".card");
      const open = card.dataset.open !== "true";
      card.dataset.open = String(open);
      btn.setAttribute("aria-expanded", String(open));
    });
  });
};
