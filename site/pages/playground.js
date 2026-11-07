// playground: counter, todo list, accent colour picker. Owner: Kendrick's Claude.
(window.pages ||= {}).playground = (el) => {
  const load = (k, d) => { try { return JSON.parse(localStorage.getItem("pg-" + k)) ?? d; } catch { return d; } };
  const save = (k, v) => localStorage.setItem("pg-" + k, JSON.stringify(v));
  const esc = (s) => s.replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);
  let count = load("count", 0), todos = load("todos", []), accent = load("accent", null);
  if (accent) document.documentElement.style.setProperty("--accent", accent);

  el.innerHTML = `
    <style>
      #view .playground-page { display: grid; gap: 16px; padding: 1rem; max-width: var(--max); margin: 0 auto;
        grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); }
      #view .playground-page h2 { grid-column: 1 / -1; margin: 0; }
      #view .playground-page .w { background: var(--surface); border-radius: var(--radius); padding: 1.25rem; }
      #view .playground-page h3 { margin: 0 0 .75rem; color: var(--accent); }
      #view .playground-page button { background: var(--accent); color: var(--bg); border: 0; border-radius: 8px;
        padding: .4rem .8rem; font: inherit; cursor: pointer; }
      #view .playground-page input[type=text] { background: var(--bg); color: var(--text); border: 1px solid var(--muted);
        border-radius: 8px; padding: .4rem .6rem; font: inherit; flex: 1; min-width: 0; }
      #view .playground-page .row { display: flex; gap: 8px; align-items: center; }
      #view .playground-page .num { font-size: 2.5rem; font-weight: 700; min-width: 3ch; text-align: center; }
      #view .playground-page ul { list-style: none; padding: 0; margin: .75rem 0 0; display: grid; gap: 6px; }
      #view .playground-page li { display: flex; gap: 8px; align-items: center; }
      #view .playground-page li.done span { text-decoration: line-through; color: var(--muted); }
      #view .playground-page li span { flex: 1; }
      #view .playground-page input[type=color] { width: 56px; height: 40px; border: 0; background: none; padding: 0; }
    </style>
    <section class="playground-page">
      <h2>Playground</h2>
      <div class="w" id="pg-counter"><h3>Counter</h3>
        <div class="row"><button class="dec" aria-label="Decrease">-</button><span class="num" aria-live="polite"></span>
        <button class="inc" aria-label="Increase">+</button><button class="reset">Reset</button></div></div>
      <div class="w" id="pg-todo"><h3>Todo list</h3>
        <form class="row"><input type="text" placeholder="Add a task" aria-label="New task"><button>Add</button></form>
        <ul></ul></div>
      <div class="w" id="pg-color"><h3>Accent colour</h3>
        <div class="row"><input type="color" aria-label="Accent colour"><button class="reset">Reset</button></div></div>
    </section>`;

  const $ = (s) => el.querySelector(s);
  const num = $("#pg-counter .num");
  const setCount = (n) => { count = n; num.textContent = n; save("count", n); };
  setCount(count);
  $("#pg-counter .inc").onclick = () => setCount(count + 1);
  $("#pg-counter .dec").onclick = () => setCount(count - 1);
  $("#pg-counter .reset").onclick = () => setCount(0);

  const ul = $("#pg-todo ul");
  const drawTodos = () => {
    ul.innerHTML = todos.map((t, i) => `<li class="${t.done ? "done" : ""}"><input type="checkbox" data-i="${i}" ${t.done ? "checked" : ""} aria-label="Done">
      <span>${esc(t.text)}</span><button data-del="${i}" aria-label="Delete">x</button></li>`).join("");
    save("todos", todos);
  };
  drawTodos();
  $("#pg-todo form").onsubmit = (e) => {
    e.preventDefault();
    const inp = e.target.querySelector("input"), text = inp.value.trim();
    if (text) { todos.push({ text, done: false }); inp.value = ""; drawTodos(); }
  };
  ul.onclick = (e) => {
    if (e.target.dataset.del != null) todos.splice(+e.target.dataset.del, 1);
    else if (e.target.dataset.i != null) todos[+e.target.dataset.i].done = e.target.checked;
    else return;
    drawTodos();
  };

  const picker = $("#pg-color input");
  const root = document.documentElement.style;
  picker.value = accent || "#38bdf8";
  picker.oninput = () => { accent = picker.value; root.setProperty("--accent", accent); save("accent", accent); };
  $("#pg-color .reset").onclick = () => { accent = null; root.removeProperty("--accent"); localStorage.removeItem("pg-accent"); picker.value = "#38bdf8"; };
};
