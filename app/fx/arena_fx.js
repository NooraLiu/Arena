/* Arena dice + random-event effects, shared by app/play.html, app/artifact_play.html and the
   animation preview. Inlined into those pages by app/fx/build.py -- edit this file, then run it.

   Needs from the page: $(id), ZC (zone -> map cell class). Dice use three.js (global THREE) when
   it loaded, and fall back to flat SVG dice without it. */

function randInt(n) { const a = new Uint32Array(1); crypto.getRandomValues(a); return 1 + (a[0] % n); }
const REDUCED = () => !!(window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches);

/* ======================= dice ======================= */

/* Flat fallback: an N-sided polygon (d2 = coin), used only when WebGL/three.js is unavailable. */
function dieSVG(faces, value) {
  if (faces <= 2) return `<svg viewBox="-34 -34 68 68"><circle class="shape" r="28"></circle><text class="num">${value ?? "?"}</text></svg>`;
  const n = Math.min(faces, 12), r = 30, pts = [];
  for (let i = 0; i < n; i++) { const a = -Math.PI / 2 + i * 2 * Math.PI / n; pts.push(`${(r * Math.cos(a)).toFixed(1)},${(r * Math.sin(a)).toFixed(1)}`); }
  return `<svg viewBox="-34 -34 68 68"><polygon class="shape" points="${pts.join(" ")}"></polygon><text class="num">${value ?? "?"}</text></svg>`;
}
function diceHTML(faces, n, values) {
  const best = values ? Math.max(...values) : null;
  return `<div class="dice">${Array.from({length: n}, (_, i) => {
    const v = values ? values[i] : null;
    return `<div class="die ${faces <= 2 ? "coin" : ""} ${values && n > 1 && v === best && values.indexOf(v) === i ? "best" : ""}">${dieSVG(faces, v)}<span class="dn">${faces <= 2 ? "硬币 d2" : "d" + faces}</span></div>`;
  }).join("")}</div>`;
}

/* Real dice in a felt tray. Dice3D.mount(el, faces, n, values|null) draws them idle (spinning
   gently, waiting for a roll) or resting on `values`; Dice3D.roll(el, faces, n, values) throws
   them and resolves once they have landed on those faces. */
const Dice3D = (() => {
  let current = null;                                   // one tray on screen at a time
  const has3D = () => typeof THREE !== "undefined" && (() => {
    try { const c = document.createElement("canvas"); return !!(c.getContext("webgl2") || c.getContext("webgl")); } catch (e) { return false; }
  })();

  // physical die for an N-sided roll; labels go on `faces` of the solid, in order
  function solidFor(faces) {
    const T = THREE;
    if (faces <= 2) return {geo: new T.CylinderGeometry(1.05, 1.05, 0.2, 56), labels: [1, 2], coin: true, rest: 0.1};
    if (faces === 3) return {geo: new T.BoxGeometry(1.3, 1.3, 1.3), labels: [1, 2, 3, 1, 2, 3], rest: 0.65};
    if (faces === 4) return {geo: new T.TetrahedronGeometry(1.25), labels: [1, 2, 3, 4], rest: 0.42};
    if (faces === 5) return {geo: new T.CylinderGeometry(0.95, 0.95, 1.25, 3), labels: [1, 2, 3, 4, 5], rest: 0.48};
    if (faces === 6) return {geo: new T.BoxGeometry(1.3, 1.3, 1.3), labels: [1, 2, 3, 4, 5, 6], rest: 0.65};
    if (faces === 7) return {geo: new T.CylinderGeometry(0.9, 0.9, 0.95, 5), labels: [1, 2, 3, 4, 5, 6, 7], rest: 0.48};
    if (faces === 8) return {geo: new T.OctahedronGeometry(1.15), labels: [1, 2, 3, 4, 5, 6, 7, 8], rest: 0.66};
    const geo = faces <= 12 ? new T.DodecahedronGeometry(1.05) : new T.IcosahedronGeometry(1.1);
    return {geo, labels: Array.from({length: faces <= 12 ? 12 : 20}, (_, i) => (i % faces) + 1), rest: 0.84};
  }

  function faceTexture(label, sides, coin) {
    const c = document.createElement("canvas"); c.width = c.height = 256;
    const g = c.getContext("2d");
    if (coin) {
      const grd = g.createRadialGradient(110, 100, 20, 128, 128, 140);
      grd.addColorStop(0, "#ffe9a8"); grd.addColorStop(.6, "#e0b24a"); grd.addColorStop(1, "#9c6f1e");
      g.fillStyle = grd; g.fillRect(0, 0, 256, 256);
      g.strokeStyle = "rgba(90,60,10,.55)"; g.lineWidth = 7; g.beginPath(); g.arc(128, 128, 104, 0, 7); g.stroke();
      g.strokeStyle = "rgba(255,245,210,.5)"; g.lineWidth = 2; g.beginPath(); g.arc(128, 128, 92, 0, 7); g.stroke();
      g.fillStyle = "#5a3a08";
    } else {
      const grd = g.createLinearGradient(0, 0, 256, 256);
      grd.addColorStop(0, "#fbf5e6"); grd.addColorStop(1, "#e9dcc0");
      g.fillStyle = grd; g.fillRect(0, 0, 256, 256);
      g.fillStyle = "#8e1d24";
    }
    const size = coin ? 120 : sides === 3 ? 92 : sides === 4 ? 128 : 112;
    const y = sides === 3 ? 150 : 132;                  // triangles: sit the number a bit low, in the fat part
    g.font = `800 ${size}px Georgia, "Times New Roman", serif`;
    g.textAlign = "center"; g.textBaseline = "middle";
    g.fillText(String(label), 128, y);
    if (label === 6 || label === 9) { const w = g.measureText(String(label)).width; g.fillRect(128 - w / 2, y + size * .42, w, size * .07); }
    const tex = new THREE.CanvasTexture(c); tex.anisotropy = 4; tex.encoding = THREE.sRGBEncoding;
    return tex;
  }

  // group a solid's triangles into its flat faces, give each numbered face its own texture
  function buildDie(faces) {
    const T = THREE, spec = solidFor(faces);
    const src = spec.geo.toNonIndexed(), P = src.attributes.position;
    const tris = [], groups = new Map();
    for (let i = 0; i < P.count; i += 3) {
      const p = [0, 1, 2].map(k => new T.Vector3().fromBufferAttribute(P, i + k));
      const n = new T.Vector3().subVectors(p[1], p[0]).cross(new T.Vector3().subVectors(p[2], p[0])).normalize();
      const key = [n.x, n.y, n.z, n.dot(p[0])].map(v => Math.round(v * 100)).join(",");
      if (!groups.has(key)) groups.set(key, {n, tris: []});
      groups.get(key).tris.push(p);
    }
    let faceList = [...groups.values()];
    if (spec.coin) faceList.sort((f1, f2) => Math.abs(f2.n.y) - Math.abs(f1.n.y));   // the two caps first
    const pos = [], uv = [], bodyMat = new T.MeshStandardMaterial({color: spec.coin ? 0xc99a36 : 0xe8d9b8, roughness: .5, metalness: spec.coin ? .55 : .04});
    const mats = [bodyMat], geo = new T.BufferGeometry(), numbered = [];
    let vi = 0;
    faceList.forEach((f, fi) => {
      const verts = []; f.tris.flat().forEach(v => { if (!verts.some(w => w.distanceTo(v) < 1e-4)) verts.push(v); });
      const c = verts.reduce((s, v) => s.add(v), new T.Vector3()).multiplyScalar(1 / verts.length);
      const a = new T.Vector3().subVectors(verts[0], c); a.sub(f.n.clone().multiplyScalar(a.dot(f.n))).normalize();
      const b = new T.Vector3().crossVectors(f.n, a);
      const R = Math.max(...verts.map(v => v.distanceTo(c)));
      const label = fi < spec.labels.length ? spec.labels[fi] : null;
      if (label !== null) { mats.push(new T.MeshStandardMaterial({map: faceTexture(label, verts.length, spec.coin), roughness: .45, metalness: spec.coin ? .5 : .02}));
                            numbered.push({n: f.n.clone(), a, b, label}); }
      const start = vi;
      f.tris.forEach(tri => tri.forEach(v => {
        pos.push(v.x, v.y, v.z);
        const d = new T.Vector3().subVectors(v, c);
        uv.push(.5 + d.dot(a) / (2.05 * R), .5 + d.dot(b) / (2.05 * R)); vi++;
      }));
      geo.addGroup(start, vi - start, label === null ? 0 : mats.length - 1);
    });
    geo.setAttribute("position", new T.Float32BufferAttribute(pos, 3));
    geo.setAttribute("uv", new T.Float32BufferAttribute(uv, 2));
    geo.computeVertexNormals();
    const mesh = new T.Mesh(geo, mats);
    mesh.add(new T.LineSegments(new T.EdgesGeometry(geo, 25), new T.LineBasicMaterial({color: spec.coin ? 0x7a5412 : 0xb8a37c})));
    return {mesh, numbered, rest: spec.rest, coin: !!spec.coin};
  }

  function shadowTexture() {
    const c = document.createElement("canvas"); c.width = c.height = 128;
    const g = c.getContext("2d"), grd = g.createRadialGradient(64, 64, 4, 64, 64, 62);
    grd.addColorStop(0, "rgba(0,0,0,.55)"); grd.addColorStop(1, "rgba(0,0,0,0)");
    g.fillStyle = grd; g.fillRect(0, 0, 128, 128);
    return new THREE.CanvasTexture(c);
  }

  // rotation that turns face `f` toward the camera, text upright
  function restingQuat(f, dir, up) {
    const T = THREE, z = dir.clone().normalize();
    const y = up.clone().sub(z.clone().multiplyScalar(up.dot(z))).normalize(), x = new T.Vector3().crossVectors(y, z);
    const world = new T.Matrix4().makeBasis(x, y, z), local = new T.Matrix4().makeBasis(f.a, f.b, f.n).transpose();
    return new T.Quaternion().setFromRotationMatrix(world.multiply(local));
  }

  function mount(el, faces, n, values, rolling) {
    if (current) current.dispose();
    if (!has3D()) { el.innerHTML = diceHTML(faces, n, values); return null; }
    const T = THREE, w = el.clientWidth || 320, h = el.clientHeight || 190;
    const renderer = new T.WebGLRenderer({antialias: true, alpha: true});
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2)); renderer.setSize(w, h);
    renderer.outputEncoding = T.sRGBEncoding;
    el.innerHTML = ""; el.appendChild(renderer.domElement);
    const cap = document.createElement("div"); cap.className = "tray-cap";
    cap.textContent = (faces <= 2 ? "硬币 d2" : "d" + faces) + (n > 1 ? ` × ${n},取大` : ""); el.appendChild(cap);
    const scene = new T.Scene(), camera = new T.PerspectiveCamera(30, w / h, .1, 100);
    camera.position.set(0, 5.6, 5.2); camera.lookAt(0, .75, .55);
    scene.add(new T.HemisphereLight(0xfff1dc, 0x1f3a2c, .55));
    const key = new T.DirectionalLight(0xfff6ea, .62); key.position.set(-2.5, 7, 3.5); scene.add(key);
    const fill = new T.DirectionalLight(0xffe2b8, .32); fill.position.set(4, 2.5, 2); scene.add(fill);
    const rim = new T.DirectionalLight(0xbfe3ff, .25); rim.position.set(-4, 3, -5); scene.add(rim);
    const shadowTex = shadowTexture(), spread = n > 1 ? 1.6 : 0, dice = [];
    for (let i = 0; i < n; i++) {
      const d = buildDie(faces);
      const shadow = new T.Mesh(new T.PlaneGeometry(2.2, 2.2), new T.MeshBasicMaterial({map: shadowTex, transparent: true, depthWrite: false}));
      shadow.rotation.x = -Math.PI / 2; shadow.position.y = .001;
      scene.add(d.mesh); scene.add(shadow);
      d.shadow = shadow; d.home = new T.Vector3((i - (n - 1) / 2) * spread * 1.25, d.rest, .35);
      d.mesh.position.copy(d.home);
      d.idleAxis = new T.Vector3(Math.random() - .5, 1, Math.random() - .5).normalize();
      d.yaw = (Math.random() - .5) * .6;
      d.mesh.quaternion.setFromAxisAngle(new T.Vector3(1, .3, .2).normalize(), Math.random() * 6);
      dice.push(d);
    }
    const dir = i => new T.Vector3().subVectors(camera.position, dice[i].home);
    const settle = (d, i, v) => {
      const f = d.numbered.find(x => x.label === v) || d.numbered[0];
      const q = restingQuat(f, new T.Vector3(0, 1, 0).lerp(dir(i).normalize(), d.coin ? .3 : .45), new T.Vector3(0, 0, -1));
      return new T.Quaternion().setFromAxisAngle(new T.Vector3(0, 1, 0), d.yaw).multiply(q);   // a little twist, like a real throw
    };
    let raf = 0, dead = false;
    const draw = () => renderer.render(scene, camera);
    const placeShadow = d => { const up = Math.max(0, d.mesh.position.y - d.rest); d.shadow.position.set(d.mesh.position.x, .001, d.mesh.position.z);
                               const s = 1 + up * .35; d.shadow.scale.set(s, s, 1); d.shadow.material.opacity = Math.max(.15, .9 - up * .25); };
    const handle = {
      dispose() { dead = true; cancelAnimationFrame(raf); renderer.dispose(); if (current === handle) current = null; },
      rest(vals) { cancelAnimationFrame(raf); dice.forEach((d, i) => { d.mesh.position.copy(d.home); d.mesh.quaternion.copy(settle(d, i, vals[i])); placeShadow(d); }); draw(); },
      idle() {
        const t0 = performance.now();
        const loop = now => { if (dead) return; const t = (now - t0) / 1000;
          dice.forEach(d => { d.mesh.position.y = d.home.y + .12 + Math.sin(t * 2.2) * .08;
            d.mesh.quaternion.multiply(new T.Quaternion().setFromAxisAngle(d.idleAxis, .012)); placeShadow(d); });
          draw(); raf = requestAnimationFrame(loop); };
        raf = requestAnimationFrame(loop);
      },
      roll(vals) {
        cancelAnimationFrame(raf);
        if (REDUCED()) { handle.rest(vals); return Promise.resolve(); }
        return new Promise(done => {
          const D = 1700, t0 = performance.now();
          const plan = dice.map((d, i) => ({
            from: new T.Vector3(-4.2 + i * .6, 2.6 + i * .4, 2.4 - i * .5),
            axis: new T.Vector3(Math.random() - .5, Math.random() - .5, Math.random() - .5).normalize(),
            spin: 16 + Math.random() * 8, q0: d.mesh.quaternion.clone(), qEnd: settle(d, i, vals[i]),
          }));
          const loop = now => {
            if (dead) return done();
            const t = Math.min(1, (now - t0) / D);
            dice.forEach((d, i) => {
              const p = plan[i], e = 1 - Math.pow(1 - t, 3);
              d.mesh.position.lerpVectors(p.from, d.home, e);
              const bounce = Math.abs(Math.sin(t * Math.PI * 3.1)) * Math.pow(1 - t, 2.2) * 2.4;
              d.mesh.position.y = d.home.y + bounce * (d.coin ? 1.5 : 1);
              const spun = p.q0.clone().multiply(new T.Quaternion().setFromAxisAngle(p.axis, p.spin * (1 - Math.pow(1 - t, 2))));
              const k = Math.min(1, Math.max(0, (t - .5) / .5)), s = k * k * (3 - 2 * k);
              d.mesh.quaternion.copy(spun.slerp(p.qEnd, s));
              placeShadow(d);
            });
            draw();
            if (t < 1) raf = requestAnimationFrame(loop); else { handle.rest(vals); done(); }
          };
          raf = requestAnimationFrame(loop);
        });
      },
    };
    current = handle;
    if (values) handle.rest(values); else if (!rolling) handle.idle();
    return handle;
  }

  return {
    available: has3D,
    release() { if (current) current.dispose(); },
    show(el, faces, n, values) { return mount(el, faces, n, values, false); },
    roll(el, faces, n, values) {
      const hd = mount(el, faces, n, null, true);
      if (!hd) {                                         // no WebGL: the flat dice tumble instead
        el.innerHTML = diceHTML(faces, n, null);
        if (REDUCED()) { el.innerHTML = diceHTML(faces, n, values); return Promise.resolve(); }
        el.querySelectorAll(".die").forEach(d => d.classList.add("rolling"));
        return new Promise(done => { const t0 = Date.now(), tk = setInterval(() => {
          el.querySelectorAll(".num").forEach(x => x.textContent = randInt(faces));
          if (Date.now() - t0 > 1050) { clearInterval(tk); el.innerHTML = diceHTML(faces, n, values); done(); } }, 70); });
      }
      return hd.roll(values);
    },
  };
})();

/* ======================= random events ======================= */

const FX_MS = 3200;
const FX_LABEL = {E01: "🐺 变异狼群 -4", E02: "🌊 洪水:手中武器冲回牌堆", E03: "🐒 猴群:抢走已装备武器", E04: "🌪️ 沙尘暴:本回合不能移动",
                  E05: "🕊️ 和平日:无事发生", E06: "☄️ 火球 -3", E07: "🐕 饿狗:交 2 食物或 -3", E08: "🍗 盛宴:下回合中心多抽 2 张"};
const FX_DAMAGE = {E01: 4, E06: 3};

/* A tiny particle system on a canvas laid over one zone. Each effect gets (ctx, w, h, t, s):
   t in [0,1] over the effect, s = per-effect state it may keep. */
function fxCanvas(box, w, h) {
  const c = document.createElement("canvas"), dpr = Math.min(window.devicePixelRatio || 1, 2);
  c.width = w * dpr; c.height = h * dpr; c.style.cssText = `position:absolute;inset:0;width:${w}px;height:${h}px`;
  box.appendChild(c); const g = c.getContext("2d"); g.scale(dpr, dpr); return g;
}
const rnd = (a, b) => a + Math.random() * (b - a);
const ease = t => 1 - Math.pow(1 - t, 3);
function emoji(g, ch, x, y, size, rot, alpha) {
  g.save(); g.globalAlpha = alpha ?? 1; g.translate(x, y); if (rot) g.rotate(rot);
  g.font = `${size}px "Apple Color Emoji","Segoe UI Emoji","Noto Color Emoji",sans-serif`; g.textAlign = "center"; g.textBaseline = "middle";
  g.fillText(ch, 0, 0); g.restore();
}
function particles(s, key, n, make) { if (!s[key]) s[key] = Array.from({length: n}, make); return s[key]; }
function drawParts(g, parts, dt, gravity) {
  parts.forEach(p => { if (p.life <= 0) return; p.vy += (gravity || 0) * dt; p.x += p.vx * dt; p.y += p.vy * dt; p.life -= dt;
    g.globalAlpha = Math.max(0, p.life / p.max) * (p.a ?? 1); g.fillStyle = p.color;
    g.beginPath(); g.arc(p.x, p.y, p.r * (p.grow ? 1 + (1 - p.life / p.max) * p.grow : 1), 0, 7); g.fill(); });
  g.globalAlpha = 1;
}
function envelope(t, inT, outT) { return Math.min(1, t / inT, (1 - t) / outT); }

const FX = {
  E01(g, w, h, t, s, dt) {                               // wolves: claw slashes, then the pack bounds through
    g.fillStyle = `rgba(160,20,20,${.28 * envelope(t, .1, .3)})`; g.fillRect(0, 0, w, h);
    const slash = Math.min(1, t / .22);
    g.strokeStyle = `rgba(255,70,70,${envelope(t, .05, .4)})`; g.lineWidth = 4; g.lineCap = "round";
    [-1, 0, 1].forEach(k => { const x0 = w * .3 + k * 16, y0 = h * .15, x1 = w * .7 + k * 16, y1 = h * .85;
      g.beginPath(); g.moveTo(x0, y0); g.lineTo(x0 + (x1 - x0) * slash, y0 + (y1 - y0) * slash); g.stroke(); });
    const dust = particles(s, "dust", 0, () => ({}));
    [0, 1, 2].forEach(i => { const tt = (t - .18 - i * .1) / .55; if (tt < 0 || tt > 1) return;
      const x = -40 + (w + 80) * tt, y = h * (.3 + .22 * i) - Math.abs(Math.sin(tt * 18)) * 10;
      emoji(g, "🐺", x, y, 30, Math.sin(tt * 18) * .12);
      if (Math.random() < .5) dust.push({x: x - 10, y: y + 12, vx: rnd(-30, -10), vy: rnd(-20, -5), r: rnd(2, 5), life: .6, max: .6, color: "#c9a26b", a: .7, grow: 1.5}); });
    drawParts(g, dust, dt, 0);
  },
  E02(g, w, h, t, s, dt) {                               // flood: two wave layers rise, bubble, then drain
    const level = h * (t < .45 ? ease(t / .45) * .82 : t < .75 ? .82 : .82 * (1 - ease((t - .75) / .25)));
    [["rgba(47,91,211,.55)", 1, 0], ["rgba(110,168,254,.55)", 1.6, 2]].forEach(([col, f, ph]) => {
      g.fillStyle = col; g.beginPath(); g.moveTo(0, h);
      for (let x = 0; x <= w; x += 4) g.lineTo(x, h - level + Math.sin(x / 18 * f + t * 14 + ph) * 5);
      g.lineTo(w, h); g.fill(); });
    const bubbles = particles(s, "b", 18, () => ({x: rnd(6, w - 6), y: h + rnd(0, 40), vy: rnd(-40, -20), r: rnd(2, 4.5)}));
    g.strokeStyle = "rgba(220,240,255,.8)"; g.lineWidth = 1.2;
    bubbles.forEach(b => { b.y += b.vy * dt; if (b.y < h - level) b.y = h + rnd(0, 10); if (level > 8) { g.beginPath(); g.arc(b.x + Math.sin(b.y / 8) * 2, b.y, b.r, 0, 7); g.stroke(); } });
    if (t > .3 && t < .8) emoji(g, "⚔️", w * .5, h - level + 6 + Math.sin(t * 20) * 3, 22, Math.sin(t * 9) * .4, envelope((t - .3) / .5, .2, .3));
  },
  E03(g, w, h, t, s) {                                   // monkeys: swing in on a vine, snatch the weapon, swing out
    g.fillStyle = `rgba(90,70,30,${.25 * envelope(t, .1, .3)})`; g.fillRect(0, 0, w, h);
    const ang = -1.2 + 2.4 * ease(Math.min(1, t / .9)), L = h * .85, ax = w * .5, ay = -h * .1;
    const mx = ax + Math.sin(ang) * L, my = ay + Math.cos(ang) * L;
    g.strokeStyle = "rgba(70,120,40,.9)"; g.lineWidth = 3; g.beginPath(); g.moveTo(ax, ay);
    g.quadraticCurveTo(ax + Math.sin(ang) * L * .5 + 6, ay + Math.cos(ang) * L * .5, mx, my); g.stroke();
    emoji(g, "🐒", mx, my + 8, 30, -ang * .4);
    const grabbed = ang > -.05;
    emoji(g, "⚔️", grabbed ? mx + 12 : w * .5, grabbed ? my + 20 : h * .62, 22, grabbed ? t * 8 : 0);
    const leaves = particles(s, "l", 10, () => ({x: rnd(0, w), y: rnd(-h, 0), vy: rnd(20, 45), sway: rnd(0, 6)}));
    leaves.forEach(p => { p.y += p.vy / 60; emoji(g, "🍃", p.x + Math.sin(p.y / 12 + p.sway) * 8, p.y, 12, p.y / 20, .8); });
  },
  E04(g, w, h, t, s, dt) {                               // sandstorm: fog bands and hundreds of streaking grains
    const k = envelope(t, .15, .25);
    for (let i = 0; i < 3; i++) { g.fillStyle = `rgba(201,162,107,${.22 * k})`; g.beginPath();
      for (let x = 0; x <= w; x += 6) g.lineTo(x, h * (.25 + i * .25) + Math.sin(x / 25 + t * 10 + i) * 10);
      g.lineTo(w, h); g.lineTo(0, h); g.fill(); }
    const sand = particles(s, "s", 260, () => ({x: rnd(-w, w), y: rnd(0, h), v: rnd(180, 420), len: rnd(4, 14)}));
    g.strokeStyle = `rgba(245,215,160,${.8 * k})`; g.lineWidth = 1.3;
    sand.forEach(p => { p.x += p.v * dt; if (p.x > w + 20) p.x = rnd(-60, -10); const y = p.y + Math.sin(p.x / 30 + t * 6) * 6;
      g.beginPath(); g.moveTo(p.x, y); g.lineTo(p.x - p.len, y + 1.5); g.stroke(); });
    emoji(g, "🌪️", w * .5 + Math.sin(t * 12) * 10, h * .45, 34, Math.sin(t * 30) * .15, k);
    if (t > .35) emoji(g, "🔒", w * .5, h * .78, 18, 0, k);
  },
  E05(g, w, h, t, s, dt) {                               // peace: soft light rays, drifting petals, a dove
    const k = envelope(t, .2, .3);
    g.save(); g.translate(w * .5, -10); g.rotate(t * .4);
    for (let i = 0; i < 7; i++) { g.rotate(Math.PI / 7); g.fillStyle = `rgba(190,255,220,${.12 * k})`;
      g.beginPath(); g.moveTo(0, 0); g.lineTo(-14, h * 1.4); g.lineTo(14, h * 1.4); g.fill(); }
    g.restore();
    const petals = particles(s, "p", 14, () => ({x: rnd(0, w), y: rnd(-h, 0), vy: rnd(18, 34), ph: rnd(0, 6)}));
    petals.forEach(p => { p.y += p.vy * dt; emoji(g, "🌸", p.x + Math.sin(p.y / 14 + p.ph) * 9, p.y, 11, p.y / 30, .85 * k); });
    emoji(g, "🕊️", w * .2 + w * .6 * t, h * .7 - h * .55 * ease(t) + Math.sin(t * 22) * 4, 28, 0, k);
  },
  E06(g, w, h, t, s, dt) {                               // fireballs: glowing streaks, impact flash, sparks, scorch
    const falls = particles(s, "f", 3, (_, i) => ({x0: rnd(-.2, .3) * w + i * w * .28, tx: w * (.25 + .25 * i) + rnd(-10, 10), ty: h * rnd(.55, .75), t0: .05 + i * .12}));
    const sparks = particles(s, "sp", 0, () => ({}));
    falls.forEach(f => {
      const tt = (t - f.t0) / .25;
      if (tt >= 0 && tt < 1) {
        const x = f.x0 + (f.tx - f.x0) * tt, y = -30 + (f.ty + 30) * tt * tt;
        const grd = g.createLinearGradient(x - 40, y - 60, x, y);
        grd.addColorStop(0, "rgba(255,120,20,0)"); grd.addColorStop(1, "rgba(255,200,80,.9)");
        g.strokeStyle = grd; g.lineWidth = 7; g.lineCap = "round"; g.beginPath(); g.moveTo(x - (f.tx - f.x0) * .25, y - 55); g.lineTo(x, y); g.stroke();
        const glow = g.createRadialGradient(x, y, 0, x, y, 14); glow.addColorStop(0, "#fff6c0"); glow.addColorStop(.5, "#ff9a2a"); glow.addColorStop(1, "rgba(255,80,0,0)");
        g.fillStyle = glow; g.beginPath(); g.arc(x, y, 14, 0, 7); g.fill();
      } else if (tt >= 1 && !f.hit) {
        f.hit = true; f.hitAt = t;
        for (let i = 0; i < 36; i++) { const a = rnd(0, 6.3), v = rnd(60, 220);
          sparks.push({x: f.tx, y: f.ty, vx: Math.cos(a) * v, vy: Math.sin(a) * v - 60, r: rnd(1.2, 3.2), life: rnd(.4, .9), max: .9, color: ["#fff2b0", "#ffb347", "#ff6a00"][i % 3]}); }
      }
      if (f.hit) {
        const k = (t - f.hitAt) / .6;
        if (k < 1) { g.strokeStyle = `rgba(255,190,90,${1 - k})`; g.lineWidth = 3; g.beginPath(); g.arc(f.tx, f.ty, 6 + k * 46, 0, 7); g.stroke();
                     g.fillStyle = `rgba(255,150,40,${.35 * (1 - k)})`; g.fillRect(0, 0, w, h); }
        g.fillStyle = `rgba(30,15,5,${.45 * envelope(t, .01, .25)})`; g.beginPath(); g.ellipse(f.tx, f.ty + 4, 16, 6, 0, 0, 7); g.fill();
      }
    });
    drawParts(g, sparks, dt, 320);
  },
  E07(g, w, h, t, s, dt) {                               // hungry dogs: dogs charge in, food flies off
    g.fillStyle = `rgba(120,60,20,${.2 * envelope(t, .1, .3)})`; g.fillRect(0, 0, w, h);
    const dust = particles(s, "d", 0, () => ({}));
    [0, 1].forEach(i => { const tt = t < .45 ? ease(t / .45) : t < .7 ? 1 : 1 - ease((t - .7) / .3);
      const x = w + 30 - (w * .55 + 30) * tt + i * 26, y = h * (.42 + i * .2) - Math.abs(Math.sin(t * 40 + i)) * 6;
      emoji(g, "🐕", x, y, 28, 0);
      if (Math.random() < .4) dust.push({x: x + 14, y: y + 12, vx: rnd(10, 40), vy: rnd(-15, 0), r: rnd(2, 4), life: .5, max: .5, color: "#b58b5a", a: .6, grow: 1.4}); });
    drawParts(g, dust, dt, 0);
    [0, 1].forEach(i => { const k = (t - .35 - i * .08) / .4; if (k < 0 || k > 1) return;
      emoji(g, "🍖", w * .5 + (i ? 1 : -1) * k * w * .35, h * .5 - Math.sin(k * Math.PI) * h * .35, 20, k * 9, 1 - k * .3); });
  },
  E08(g, w, h, t, s, dt) {                               // feast: golden rays, confetti, food raining in
    const k = envelope(t, .15, .25);
    g.save(); g.translate(w / 2, h / 2); g.rotate(t * 1.4);
    for (let i = 0; i < 12; i++) { g.rotate(Math.PI / 6); g.fillStyle = `rgba(255,209,102,${.16 * k})`;
      g.beginPath(); g.moveTo(0, 0); g.lineTo(-10, Math.max(w, h)); g.lineTo(10, Math.max(w, h)); g.fill(); }
    g.restore();
    const confetti = particles(s, "c", 40, () => ({x: rnd(0, w), y: rnd(-h, 0), vy: rnd(40, 90), vx: rnd(-20, 20), r: rnd(1.5, 3), color: ["#ffd166", "#ff8fab", "#7ee787", "#6ea8fe"][Math.floor(rnd(0, 4))], life: 9, max: 9}));
    drawParts(g, confetti, dt, 0);
    ["🍗", "🍎", "🍖", "🍉", "🥩"].forEach((ch, i) => { const tt = (t - .1 - i * .08) / .45; if (tt < 0) return;
      const x = w * (.18 + .16 * i), y = Math.min(h * .62, -20 + h * .82 * ease(Math.min(1, tt))) - (tt > 1 ? 0 : Math.sin(tt * 9) * 4);
      emoji(g, ch, x, y, 22, 0, k); });
  },
};

function floatDamage(layer, zoneEl, seats, amount) {
  const L = layer.getBoundingClientRect();
  zoneEl.querySelectorAll(".tok").forEach(tok => {
    const m = tok.textContent.match(/s(\d+)/); if (!m || !seats.includes(+m[1])) return;
    const r = tok.getBoundingClientRect(), d = document.createElement("div"); d.className = "fxdmg"; d.textContent = `-${amount}`;
    d.style.left = (r.left - L.left + r.width / 2) + "px"; d.style.top = (r.top - L.top - 6) + "px";
    layer.appendChild(d);
    d.animate([{transform: "translate(-50%,0) scale(.6)", opacity: 0}, {transform: "translate(-50%,-10px) scale(1.25)", opacity: 1, offset: .25},
               {transform: "translate(-50%,-34px) scale(1)", opacity: 0}], {duration: 1600, delay: 700, easing: "ease-out", fill: "both"});
    setTimeout(() => d.remove(), 2600);
  });
}

const FX_ZONE = {center: "中心", forest: "林区", water: "水区", stone: "石区", city: "城区"};
function playEvent(ev) {
  const layer = $("fx"); if (!layer) return;
  const L = layer.getBoundingClientRect();
  const banner = document.createElement("div"); banner.className = "fxbanner";
  banner.innerHTML = `<b>${FX_LABEL[ev.id] || ev.name}</b><span>${(ev.zones || []).map(z => FX_ZONE[z] || z).join(" · ")}</span>`;
  layer.appendChild(banner);
  banner.animate([{opacity: 0, transform: "translate(-50%,-14px)"}, {opacity: 1, transform: "translate(-50%,0)", offset: .1},
                  {opacity: 1, transform: "translate(-50%,0)", offset: .85}, {opacity: 0, transform: "translate(-50%,-8px)"}], {duration: FX_MS + 400, fill: "both"});
  setTimeout(() => banner.remove(), FX_MS + 500);
  (ev.zones || []).forEach(z => {
    const el = document.querySelector(`#map .zone.${ZC[z]}`); if (!el) return;
    const R = el.getBoundingClientRect(), w = R.width, h = R.height, b = document.createElement("div"); b.className = "fxbox";
    Object.assign(b.style, {left: (R.left - L.left) + "px", top: (R.top - L.top) + "px", width: w + "px", height: h + "px"});
    layer.appendChild(b);
    if (!REDUCED() && FX[ev.id]) {
      const g = fxCanvas(b, w, h), s = {}, t0 = performance.now(); let last = t0;
      const loop = now => { const t = Math.min(1, (now - t0) / FX_MS), dt = Math.min(.05, (now - last) / 1000); last = now;
        g.clearRect(0, 0, w, h); FX[ev.id](g, w, h, t, s, dt); if (t < 1) requestAnimationFrame(loop); };
      requestAnimationFrame(loop);
      if (ev.id === "E06" || ev.id === "E01")            // the whole zone shakes as it gets hit
        b.animate([{transform: "translate(0,0)"}, {transform: "translate(-3px,2px)"}, {transform: "translate(3px,-2px)"}, {transform: "translate(-2px,-1px)"}, {transform: "translate(0,0)"}],
                  {duration: 380, delay: ev.id === "E06" ? 420 : 250, iterations: 2});
    }
    if (FX_DAMAGE[ev.id] && ev.hits) floatDamage(layer, el, ev.hits, FX_DAMAGE[ev.id]);
    setTimeout(() => b.remove(), FX_MS + 300);
  });
}
