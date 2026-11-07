// Contact page, owned by Bekarys's Claude (issue #9).
// Form with live validation (native constraints) + live preview; submissions
// are saved to localStorage["contact-submissions"]; then a thanks state.
(window.pages ||= {}).contact = (el) => {
  const KEY = "contact-submissions";
  const load = () => { try { return JSON.parse(localStorage.getItem(KEY)) || []; } catch { return []; } };

  el.innerHTML = `
    <style>
      #view .contact-page { display: grid; gap: 1.5rem; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); }
      #view .contact-page h1 { grid-column: 1 / -1; margin: 0; }
      #view .contact-page form, #view .contact-page .card { background: var(--surface); border-radius: var(--radius); padding: 1.25rem; }
      #view .contact-page label { display: block; margin-bottom: 1rem; color: var(--muted); }
      #view .contact-page input, #view .contact-page textarea { display: block; width: 100%; margin-top: .25rem; padding: .6rem; font: inherit;
        color: var(--text); background: var(--bg); border: 1px solid var(--muted); border-radius: 8px; }
      #view .contact-page textarea { min-height: 7rem; resize: vertical; }
      #view .contact-page .touched:invalid { border-color: #f87171; }
      #view .contact-page .err { display: block; min-height: 1.2em; font-size: .85rem; color: #f87171; }
      #view .contact-page button { font: inherit; padding: .6rem 1.2rem; border: 0; border-radius: 8px; background: var(--accent); color: var(--bg); cursor: pointer; }
      #view .contact-page button:disabled { opacity: .5; cursor: not-allowed; }
      #view .contact-page .preview p { white-space: pre-wrap; word-break: break-word; }
      #view .contact-page .muted { color: var(--muted); }
    </style>
    <section class="contact-page">
      <h1>Contact</h1>
      <form novalidate>
        <label>Name <input name="name" required minlength="2" autocomplete="name"><span class="err" aria-live="polite"></span></label>
        <label>Email <input name="email" type="email" required autocomplete="email"><span class="err" aria-live="polite"></span></label>
        <label>Message <textarea name="message" required minlength="10" maxlength="1000"></textarea><span class="err" aria-live="polite"></span></label>
        <button type="submit" disabled>Send</button>
        <span class="muted count"></span>
      </form>
      <div class="card preview" aria-live="polite">
        <h2>Preview</h2>
        <p><strong class="p-name"></strong> <span class="muted p-email"></span></p>
        <p class="p-message"></p>
      </div>
    </section>`;

  const form = el.querySelector("form");
  const btn = form.querySelector("button");
  const F = form.elements;
  const fields = [...form.elements].filter((f) => f.name);
  const $ = (s) => el.querySelector(s);
  const showCount = () => { const n = load().length; $(".count").textContent = n ? ` ${n} sent from this browser` : ""; };

  const update = (e) => {
    if (e) e.target.classList.add("touched");
    for (const f of fields) {
      f.nextElementSibling.textContent = f.classList.contains("touched") ? f.validationMessage : "";
    }
    btn.disabled = !form.checkValidity();
    // textContent, never innerHTML: user input is not trusted markup.
    $(".p-name").textContent = F.name.value || "Your name";
    $(".p-email").textContent = F.email.value ? `<${F.email.value}>` : "";
    $(".p-message").textContent = F.message.value || "Your message shows up here as you type.";
  };
  form.addEventListener("input", update);

  form.addEventListener("submit", (e) => {
    e.preventDefault();
    if (!form.checkValidity()) { fields.forEach((f) => f.classList.add("touched")); return update(); }
    const entry = Object.fromEntries(fields.map((f) => [f.name, f.value.trim()]));
    entry.at = new Date().toISOString();
    try { localStorage.setItem(KEY, JSON.stringify([...load(), entry])); } catch {}
    const name = entry.name;
    el.querySelector(".contact-page").innerHTML = `
      <div class="card thanks" style="grid-column: 1 / -1; text-align: center">
        <h1>Thanks, <span class="t-name"></span>!</h1>
        <p class="muted">Your message is saved in this browser.</p>
        <button type="button">Send another</button>
      </div>`;
    $(".t-name").textContent = name;
    $(".thanks button").onclick = () => window.pages.contact(el);
  });

  update();
  showCount();
};
