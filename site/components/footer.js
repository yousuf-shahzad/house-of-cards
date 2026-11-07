// Footer, owned by Bekarys's Claude (issue #2).
// Test card: renders a credits line for every agent and what each built.
// Pass = open site/index.html, the footer lists all five credits below.
(window.components ||= {}).footer = (el) => {
  const credits = [
    ["Yousuf's Claude", "header"],
    ["Yousuf's Codex", "hero"],
    ["Kendrick's Claude", "features"],
    ["Bekarys's Claude", "footer"],
    ["Gawyn's Claude", "layout + integration"],
  ];
  el.innerHTML = `
    <style>
      #footer { background: var(--surface); color: var(--muted); margin-top: 2rem; }
      #footer ul { list-style: none; padding: 0; margin: .5rem 0 0; display: flex; flex-wrap: wrap; gap: .5rem 1.5rem; }
      #footer strong { color: var(--text); }
    </style>
    <footer>
      <p>Built by five agents on one board.</p>
      <ul>${credits.map(([who, what]) => `<li><strong>${who}</strong>: ${what}</li>`).join("")}</ul>
    </footer>`;
};
