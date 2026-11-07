// Hero: headline, tagline, and feature CTA. Owner: Yousuf's Codex.
(window.components ||= {}).hero = (el) => {
  el.innerHTML = `
    <style>
      #hero .intro { padding: clamp(32px, 8vw, 80px) 16px; text-align: center; background: transparent; }
      #hero .eyebrow { color: var(--accent); font-weight: 700; letter-spacing: .12em; text-transform: uppercase; }
      #hero h1 { max-width: 720px; margin: 16px auto; font-size: clamp(2rem, 6vw, 3.75rem); line-height: 1.1; }
      #hero .tagline { max-width: 560px; margin: 0 auto 28px; color: var(--muted); font-size: 1.15rem; }
      #hero .cta { display: inline-block; padding: 12px 24px; border-radius: var(--radius); background: var(--accent); color: var(--bg); font-weight: 700; text-decoration: none; }
      #hero .cta:hover { text-decoration: underline; }
      #hero .cta:focus-visible { outline: 3px solid var(--text); outline-offset: 4px; }
    </style>
    <section class="intro" aria-labelledby="hero-heading">
      <p class="eyebrow">One team. Shared ideas.</p>
      <h1 id="hero-heading">Build something great, together.</h1>
      <p class="tagline">Four agents, one shared workspace. Turn small contributions into a working idea, one component at a time.</p>
      <a class="cta" href="#features">Explore the features</a>
    </section>`;
};
