// header: site title + nav links. Owner: Yousuf's Claude.
(window.components ||= {}).header = (el) => {
  el.innerHTML = `
    <style>
      #header .bar { display: flex; align-items: center; justify-content: space-between;
        flex-wrap: wrap; gap: 12px; padding: 14px 20px; border-bottom: 1px solid #ddd; }
      #header .title { font-weight: 700; font-size: 1.25rem; text-decoration: none; color: inherit; }
      #header nav { display: flex; gap: 16px; }
      #header nav a { text-decoration: none; color: inherit; }
      #header nav a:hover { text-decoration: underline; }
    </style>
    <div class="bar">
      <a class="title" href="#top">Hackathon Test Site</a>
      <nav aria-label="Main">
        <a href="#hero">Home</a>
        <a href="#features">Features</a>
        <a href="#footer">Credits</a>
      </nav>
    </div>`;
};
