// features: 3 feature cards. Owner: Kendrick's Claude.
(window.components ||= {}).features = (el) => {
  const cards = [
    ["Multi-agent teamwork", "Several AI agents build one project side by side."],
    ["One shared board", "A pinned GitHub issue keeps every agent and human in sync."],
    ["Small, owned pieces", "Each agent owns one file, so merges never collide."],
  ];
  el.innerHTML = `
    <style>
      #features .grid { display: grid; gap: 16px; padding: 1rem;
        grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); max-width: var(--max); margin: 0 auto; }
      #features .card { background: var(--surface); border-radius: var(--radius); padding: 1.25rem; }
      #features h3 { margin: 0 0 .5rem; color: var(--accent); }
      #features p { margin: 0; color: var(--muted); }
    </style>
    <div class="grid">${cards.map(([t, d]) => `<div class="card"><h3>${t}</h3><p>${d}</p></div>`).join("")}</div>`;
};
