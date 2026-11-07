// Owner: Yousuf's Codex. A small incompressible velocity field advects two dyes.
(() => {
  const cleanups = new WeakMap();
  (window.components ||= {}).fluid = (el) => {
    cleanups.get(el)?.();
    el.innerHTML = `<style>
      #fluid { pointer-events: none; overflow: hidden; }
      #fluid canvas { filter: blur(10px); opacity: .65; }
    </style><canvas aria-hidden="true"></canvas>`;
    const canvas = el.querySelector('canvas');
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    const motion = matchMedia('(prefers-reduced-motion: reduce)');
    let width, height, size, u, v, dye, glow, nextU, nextV, nextDye, nextGlow;
    let pressure, nextPressure, divergence, pixels, accent, secondary;
    let frame = 0, lastTime = 0, clock = 0, home = true, previous = null;
    const color = (value) => {
      ctx.fillStyle = '#38bdf8';
      ctx.fillStyle = value.trim();
      ctx.fillRect(0, 0, 1, 1);
      return ctx.getImageData(0, 0, 1, 1).data.slice(0, 3);
    };
    function readColors() {
      const css = getComputedStyle(document.documentElement);
      accent = color(css.getPropertyValue('--accent'));
      secondary = color(css.getPropertyValue('--muted'));
    }
    function splat(x, y, dx, dy, strength = 1) {
      for (let row = Math.max(1, Math.floor(y - 7)); row < Math.min(height - 1, y + 7); row++) {
        for (let col = Math.max(1, Math.floor(x - 7)); col < Math.min(width - 1, x + 7); col++) {
          const i = row * width + col;
          const weight = Math.exp(-((col - x) ** 2 + (row - y) ** 2) / 12) * strength;
          u[i] += dx * weight; v[i] += dy * weight;
          dye[i] = Math.min(2, dye[i] + weight);
          glow[i] = Math.min(2, glow[i] + weight * (.5 + .5 * Math.sin(clock)));
        }
      }
    }
    function resize() {
      width = 96;
      height = Math.max(36, Math.min(144, Math.round(96 * innerHeight / Math.max(1, innerWidth))));
      size = width * height;
      canvas.width = width; canvas.height = height;
      [u, v, dye, glow, nextU, nextV, nextDye, nextGlow, pressure, nextPressure, divergence] =
        Array.from({ length: 11 }, () => new Float32Array(size));
      pixels = ctx.createImageData(width, height);
      readColors();
      splat(width * .3, height * .55, 1.5, -1, 1.5);
      splat(width * .7, height * .4, -1.5, 1, 1.5);
      paint();
    }
    function sample(field, x, y) {
      x = Math.max(0, Math.min(width - 1.001, x));
      y = Math.max(0, Math.min(height - 1.001, y));
      const col = Math.floor(x), row = Math.floor(y), a = x - col, b = y - row;
      const i = row * width + col;
      return (field[i] * (1 - a) + field[i + 1] * a) * (1 - b) +
        (field[i + width] * (1 - a) + field[i + width + 1] * a) * b;
    }
    function step(dt) {
      clock += dt;
      splat(width * (.5 + .22 * Math.sin(clock * .35)), height * .7, Math.cos(clock) * .3, -.35, .035);
      // Semi-Lagrangian advection remains stable when a pointer moves quickly.
      for (let y = 1; y < height - 1; y++) {
        for (let x = 1; x < width - 1; x++) {
          const i = y * width + x, px = x - u[i] * dt * 18, py = y - v[i] * dt * 18;
          nextU[i] = sample(u, px, py) * .985;
          nextV[i] = sample(v, px, py) * .985;
          nextDye[i] = sample(dye, px, py) * .994;
          nextGlow[i] = sample(glow, px, py) * .993;
        }
      }
      [u, nextU] = [nextU, u]; [v, nextV] = [nextV, v];
      [dye, nextDye] = [nextDye, dye]; [glow, nextGlow] = [nextGlow, glow];
      pressure.fill(0); nextPressure.fill(0);
      for (let y = 1; y < height - 1; y++) {
        for (let x = 1; x < width - 1; x++) {
          const i = y * width + x;
          divergence[i] = -.5 * (u[i + 1] - u[i - 1] + v[i + width] - v[i - width]);
        }
      }
      // Pressure projection removes divergence so dye flows instead of expanding.
      for (let pass = 0; pass < 12; pass++) {
        for (let y = 1; y < height - 1; y++) {
          for (let x = 1; x < width - 1; x++) {
            const i = y * width + x;
            nextPressure[i] = (divergence[i] + pressure[i - 1] + pressure[i + 1] + pressure[i - width] + pressure[i + width]) / 4;
          }
        }
        [pressure, nextPressure] = [nextPressure, pressure];
      }
      for (let y = 1; y < height - 1; y++) {
        for (let x = 1; x < width - 1; x++) {
          const i = y * width + x;
          u[i] -= .5 * (pressure[i + 1] - pressure[i - 1]);
          v[i] -= .5 * (pressure[i + width] - pressure[i - width]);
        }
      }
    }
    function paint() {
      for (let i = 0; i < size; i++) {
        const mix = Math.min(1, glow[i]), alpha = Math.min(1, dye[i]);
        for (let c = 0; c < 3; c++) pixels.data[i * 4 + c] = accent[c] * (1 - mix) + secondary[c] * mix;
        pixels.data[i * 4 + 3] = alpha * 230;
      }
      ctx.putImageData(pixels, 0, 0);
    }
    function tick(time) {
      frame = 0;
      if (!home || document.hidden || motion.matches) return;
      if (!lastTime || time - lastTime >= 1000 / 30) {
        step(lastTime ? Math.min(.05, (time - lastTime) / 1000) : 1 / 30);
        lastTime = time; paint();
      }
      frame = requestAnimationFrame(tick);
    }
    function sync() {
      cancelAnimationFrame(frame); frame = 0; lastTime = 0; previous = null;
      if (home && !document.hidden && !motion.matches) frame = requestAnimationFrame(tick);
    }
    function route(event) { home = event.detail?.route === 'home'; sync(); }
    function pointer(event) {
      if (!home || document.hidden || motion.matches) return;
      const x = event.clientX / Math.max(1, innerWidth) * width;
      const y = event.clientY / Math.max(1, innerHeight) * height;
      const dx = previous && previous.id === event.pointerId ? Math.max(-4, Math.min(4, x - previous.x)) : 0;
      const dy = previous && previous.id === event.pointerId ? Math.max(-4, Math.min(4, y - previous.y)) : -.5;
      splat(x, y, dx, dy, .8);
      previous = { x, y, id: event.pointerId };
    }
    function release() { previous = null; }
    const colors = new MutationObserver(() => { readColors(); paint(); });
    colors.observe(document.documentElement, { attributes: true, attributeFilter: ['style', 'class'] });
    window.addEventListener('pointermove', pointer, { passive: true });
    window.addEventListener('pointerdown', pointer, { passive: true });
    window.addEventListener('pointerup', release);
    window.addEventListener('pointercancel', release);
    window.addEventListener('resize', resize);
    window.addEventListener('routechange', route);
    document.addEventListener('visibilitychange', sync);
    motion.addEventListener('change', sync);
    cleanups.set(el, () => {
      cancelAnimationFrame(frame); colors.disconnect();
      window.removeEventListener('pointermove', pointer); window.removeEventListener('pointerdown', pointer);
      window.removeEventListener('pointerup', release); window.removeEventListener('pointercancel', release);
      window.removeEventListener('resize', resize); window.removeEventListener('routechange', route);
      document.removeEventListener('visibilitychange', sync); motion.removeEventListener('change', sync);
    });
    resize(); sync();
  };
})();
