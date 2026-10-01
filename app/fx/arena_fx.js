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

/* Dice in the style of a big "moment" roll: one large gem-like die floats over an arcane circle,
   spins hard in place, slows, wobbles and settles with the rolled face toward you, and the
   number flares. Only real dice shapes: coin (d2), d4 (a pyramid read at the top corner), d6,
   d8, d10, d12, d20. Rolls with no die of their own use the usual stand-ins: d3 = d6 marked
   1-3 twice, d5 = d10 marked 1-5 twice, d7 = d8 (an 8 is thrown again, before the dice leave
   your hand -- so the die simply never lands on 8).
   Dice3D.show(el, faces, n, values|null) draws them idle or resting; Dice3D.roll(el, faces, n,
   values) plays the roll and resolves when they have landed on `values`. */
const Dice3D = (() => {
  let current = null;
  const has3D = () => typeof THREE !== "undefined" && (() => {
    try { const c = document.createElement("canvas"); return !!(c.getContext("webgl2") || c.getContext("webgl")); } catch (e) { return false; }
  })();
  const GOLD = "#f3c969", GEM = ["#3b2466", "#1c1033"];

  // which physical die a roll uses, and what is printed on it
  function kind(faces) {
    if (faces <= 2) return {shape: "coin", labels: [1, 2], name: "硬币 d2"};
    if (faces === 3) return {shape: "d6", labels: [1, 3, 2, 2, 3, 1], name: "d3 · 六面骰印两遍 1–3"};
    if (faces === 4) return {shape: "d4", labels: [1, 2, 3, 4], name: "d4"};
    if (faces === 5) return {shape: "d10", labels: [1, 2, 3, 4, 5, 1, 2, 3, 4, 5], name: "d5 · 十面骰印两遍 1–5"};
    if (faces === 6) return {shape: "d6", labels: [1, 6, 2, 5, 3, 4], name: "d6"};
    if (faces === 7) return {shape: "d8", labels: [1, 8, 2, 7, 3, 6, 4, 5], name: "d7 · 八面骰,掷到 8 重掷"};
    if (faces === 8) return {shape: "d8", labels: [1, 8, 2, 7, 3, 6, 4, 5], name: "d8"};
    if (faces <= 10) return {shape: "d10", labels: Array.from({length: 10}, (_, i) => (i % faces) + 1), name: "d" + faces};
    if (faces <= 12) return {shape: "d12", labels: Array.from({length: 12}, (_, i) => (i % faces) + 1), name: "d" + faces};
    return {shape: "d20", labels: Array.from({length: 20}, (_, i) => (i % faces) + 1), name: "d" + faces};
  }

  function d10Geometry(r) {                            // pentagonal trapezohedron: 10 planar kites
    const T = THREE, H = r, z = r * 0.1055728, pts = [];   // z solved so each kite is flat for apex height = r
    const U = k => new T.Vector3(Math.cos(k * 2 * Math.PI / 5) * r, z, Math.sin(k * 2 * Math.PI / 5) * r);
    const L = k => new T.Vector3(Math.cos((k + .5) * 2 * Math.PI / 5) * r, -z, Math.sin((k + .5) * 2 * Math.PI / 5) * r);
    const top = new T.Vector3(0, H, 0), bot = new T.Vector3(0, -H, 0);
    const quad = (a, b, c, d) => pts.push(a, b, c, a, c, d);
    for (let k = 0; k < 5; k++) { quad(top, U(k + 1), L(k), U(k)); quad(bot, L(k), U(k + 1), L(k + 1)); }
    const g = new T.BufferGeometry().setFromPoints(pts); g.computeVertexNormals(); return g;
  }
  function solid(shape) {
    const T = THREE;
    return {coin: () => new T.CylinderGeometry(1.25, 1.25, .22, 64), d4: () => new T.TetrahedronGeometry(1.45),
            d6: () => new T.BoxGeometry(1.55, 1.55, 1.55), d8: () => new T.OctahedronGeometry(1.35),
            d10: () => d10Geometry(1.25), d12: () => new T.DodecahedronGeometry(1.3), d20: () => new T.IcosahedronGeometry(1.35)}[shape]();
  }

  // a face's picture: gem ground, engraved gold numerals; `marks` = [{text, x, y, rot, size}] in 0..256
  function faceTextures(marks, coin) {
    const mk = () => { const c = document.createElement("canvas"); c.width = c.height = 256; return [c, c.getContext("2d")]; };
    const [c, g] = mk(), [e, ge] = mk();
    if (coin) {
      const grd = g.createRadialGradient(100, 90, 10, 128, 128, 150);
      grd.addColorStop(0, "#fff0b8"); grd.addColorStop(.55, "#d9a43e"); grd.addColorStop(1, "#7d5310");
      g.fillStyle = grd; g.fillRect(0, 0, 256, 256);
      for (const [rad, col, lw] of [[110, "rgba(90,58,8,.7)", 6], [96, "rgba(255,240,200,.55)", 2]]) { g.strokeStyle = col; g.lineWidth = lw; g.beginPath(); g.arc(128, 128, rad, 0, 7); g.stroke(); }
    } else {
      const grd = g.createRadialGradient(95, 80, 10, 128, 128, 170);
      grd.addColorStop(0, "#5a3a92"); grd.addColorStop(.6, GEM[0]); grd.addColorStop(1, GEM[1]);
      g.fillStyle = grd; g.fillRect(0, 0, 256, 256);
      g.globalAlpha = .12; for (let i = 0; i < 40; i++) { g.fillStyle = i % 2 ? "#b58cff" : "#000"; g.beginPath(); g.arc(Math.random() * 256, Math.random() * 256, Math.random() * 18, 0, 7); g.fill(); }
      g.globalAlpha = 1;
    }
    ge.fillStyle = "#000"; ge.fillRect(0, 0, 256, 256);
    marks.forEach(m => {
      for (const [ctx, fill, stroke] of [[g, coin ? "#5a3806" : GOLD, coin ? "rgba(255,240,200,.5)" : "rgba(20,8,40,.9)"], [ge, "#fff", null]]) {
        ctx.save(); ctx.translate(m.x, m.y); ctx.rotate(m.rot || 0);
        ctx.font = `700 ${m.size}px "Cinzel","Trajan Pro",Georgia,"Times New Roman",serif`; ctx.textAlign = "center"; ctx.textBaseline = "middle";
        if (stroke) { ctx.lineWidth = m.size * .09; ctx.strokeStyle = stroke; ctx.strokeText(m.text, 0, 0); }
        ctx.fillStyle = fill; ctx.fillText(m.text, 0, 0);
        if (m.text === "6" || m.text === "9") { const w = ctx.measureText(m.text).width; ctx.fillRect(-w / 2, m.size * .42, w, m.size * .07); }
        ctx.restore();
      }
    });
    const tex = t => { const x = new THREE.CanvasTexture(t); x.anisotropy = 4; x.encoding = THREE.sRGBEncoding; return x; };
    return {map: tex(c), emissiveMap: tex(e)};
  }

  function buildDie(faces) {
    const T = THREE, K = kind(faces), coin = K.shape === "coin";
    const src = solid(K.shape).toNonIndexed(), P = src.attributes.position, groups = new Map();
    for (let i = 0; i < P.count; i += 3) {
      const p = [0, 1, 2].map(k => new T.Vector3().fromBufferAttribute(P, i + k));
      const n = new T.Vector3().subVectors(p[1], p[0]).cross(new T.Vector3().subVectors(p[2], p[0])).normalize();
      const key = [n.x, n.y, n.z, n.dot(p[0])].map(v => Math.round(v * 100)).join(",");
      if (!groups.has(key)) groups.set(key, {n, tris: []});
      groups.get(key).tris.push(p);
    }
    let list = [...groups.values()];
    if (coin) list.sort((f1, f2) => Math.abs(f2.n.y) - Math.abs(f1.n.y));        // the two caps first
    else {                                                                         // opposite faces get paired labels
      const ordered = [];
      list.forEach(f => { if (ordered.includes(f)) return; const o = list.find(g => g !== f && !ordered.includes(g) && g.n.dot(f.n) < -.99); ordered.push(f); if (o) ordered.push(o); });
      list = ordered;
    }
    const faceInfo = list.map(f => {
      const verts = []; f.tris.flat().forEach(v => { if (!verts.some(w => w.distanceTo(v) < 1e-4)) verts.push(v); });
      const c = verts.reduce((s, v) => s.add(v), new T.Vector3()).multiplyScalar(1 / verts.length);
      // which way is "up" on this face: triangles point up (like a real d8/d20), d10 kites point their long tip up,
      // squares and pentagons sit on an edge
      let up;
      if (verts.length === 3 || coin) up = new T.Vector3().subVectors(verts[0], c);
      else if (K.shape === "d10") up = new T.Vector3().subVectors(verts.reduce((m, v) => v.distanceTo(c) > m.distanceTo(c) ? v : m), c);
      else { const nb = verts.slice(1).reduce((m, v) => v.distanceTo(verts[0]) < m.distanceTo(verts[0]) ? v : m);
             up = new T.Vector3().addVectors(verts[0], nb).multiplyScalar(.5).sub(c); }
      const b = up.sub(f.n.clone().multiplyScalar(up.dot(f.n))).normalize();
      return {f, verts, c, a: new T.Vector3().crossVectors(b, f.n), b, R: Math.max(...verts.map(v => v.distanceTo(c)))};
    });
    const uvOf = (fi, v) => { const d = new T.Vector3().subVectors(v, fi.c); return [.5 + d.dot(fi.a) / (2.05 * fi.R), .5 + d.dot(fi.b) / (2.05 * fi.R)]; };
    // d4 is read at the corner that points up: every face carries its three corners' numbers
    const corners = K.shape === "d4" ? [] : null;
    if (corners) faceInfo.forEach(fi => fi.verts.forEach(v => { if (!corners.some(c => c.v.distanceTo(v) < 1e-4)) corners.push({v: v.clone(), label: K.labels[corners.length]}); }));
    const body = coin ? new T.MeshStandardMaterial({color: 0xc99a36, metalness: .85, roughness: .3})
                      : new T.MeshPhysicalMaterial({color: 0x2c1a4d, metalness: .1, roughness: .22, clearcoat: 1, clearcoatRoughness: .08});
    const mats = [body], pos = [], uv = [], geo = new T.BufferGeometry(), numbered = [];
    let vi = 0;
    faceInfo.forEach((fi, idx) => {
      let marks = null, label = null;
      if (corners) {
        marks = fi.verts.map(v => { const [u, w] = uvOf(fi, v), [cu, cw] = [.5, .5];
          const x = (cu + (u - cu) * .58) * 256, y = (1 - (cw + (w - cw) * .58)) * 256, dx = (u - cu) * 256, dy = -(w - cw) * 256;
          return {text: String(corners.find(c => c.v.distanceTo(v) < 1e-4).label), x, y, rot: Math.atan2(dx, -dy), size: 68}; });
      } else if (idx < K.labels.length) {
        label = K.labels[idx];
        const n = fi.verts.length, size = coin ? 130 : n === 3 ? (K.shape === "d20" ? 84 : 100) : n === 4 && K.shape === "d10" ? 66 : n === 4 ? 128 : 104;
        marks = [{text: String(label), x: 128, y: 132, size}];
      }
      if (marks) { const tx = faceTextures(marks, coin);
        mats.push(coin ? new T.MeshStandardMaterial({map: tx.map, metalness: .75, roughness: .32, emissive: 0x3a2400, emissiveMap: tx.emissiveMap, emissiveIntensity: .4})
                       : new T.MeshPhysicalMaterial({map: tx.map, metalness: .1, roughness: .22, clearcoat: 1, clearcoatRoughness: .08,
                                                      emissive: new T.Color(GOLD), emissiveMap: tx.emissiveMap, emissiveIntensity: .55})); }
      if (label !== null) numbered.push({n: fi.f.n.clone(), a: fi.a, b: fi.b, label});
      const start = vi;
      fi.f.tris.forEach(tri => tri.forEach(v => { pos.push(v.x, v.y, v.z); uv.push(...uvOf(fi, v)); vi++; }));
      geo.addGroup(start, vi - start, marks ? mats.length - 1 : 0);
    });
    geo.setAttribute("position", new T.Float32BufferAttribute(pos, 3));
    geo.setAttribute("uv", new T.Float32BufferAttribute(uv, 2));
    geo.computeVertexNormals();
    const mesh = new T.Mesh(geo, mats);
    mesh.add(new T.LineSegments(new T.EdgesGeometry(geo, 25), new T.LineBasicMaterial({color: coin ? 0x7a5412 : 0xd9ad55, transparent: true, opacity: .75})));
    // resting frames: for most dice a face turned toward you; for the d4, a corner pointing up
    const rests = corners ? corners.map(c => {
      const n = c.v.clone().normalize();
      const fc = faceInfo.find(fi => fi.verts.some(v => v.distanceTo(c.v) < 1e-4)).c.clone();
      const b = fc.sub(n.clone().multiplyScalar(fc.dot(n))).normalize().negate();
      return {n, a: new T.Vector3().crossVectors(b, n), b, label: c.label, corner: true};
    }) : numbered;
    return {mesh, rests, coin, mats, name: K.name, shape: K.shape};
  }

  function orient(f, dir, up) {                        // rotation taking frame f to (dir, up)
    const T = THREE, z = dir.clone().normalize();
    const y = up.clone().sub(z.clone().multiplyScalar(up.dot(z))).normalize(), x = new T.Vector3().crossVectors(y, z);
    return new T.Quaternion().setFromRotationMatrix(new T.Matrix4().makeBasis(x, y, z).multiply(new T.Matrix4().makeBasis(f.a, f.b, f.n).transpose()));
  }
  const spriteTex = () => { const c = document.createElement("canvas"); c.width = c.height = 64; const g = c.getContext("2d");
    const grd = g.createRadialGradient(32, 32, 0, 32, 32, 32); grd.addColorStop(0, "rgba(255,255,255,1)"); grd.addColorStop(.3, "rgba(255,220,140,.8)"); grd.addColorStop(1, "rgba(255,200,100,0)");
    g.fillStyle = grd; g.fillRect(0, 0, 64, 64); return new THREE.CanvasTexture(c); };

  function mount(el, faces, n, values, rolling) {
    if (current) current.dispose();
    el.classList.add("dstage"); el.classList.remove("revealed", "crit", "fumble");
    if (!has3D()) { el.innerHTML = diceHTML(faces, n, values); return null; }
    const T = THREE, w = el.clientWidth || 360, h = el.clientHeight || 260;
    const renderer = new T.WebGLRenderer({antialias: true, alpha: true});
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2)); renderer.setSize(w, h); renderer.outputEncoding = T.sRGBEncoding;
    el.innerHTML = `<div class="drings"></div><div class="dburst"></div>`; el.appendChild(renderer.domElement);
    const scene = new T.Scene(), camera = new T.PerspectiveCamera(30, w / h, .1, 100);
    camera.position.set(0, .7, 8.2); camera.lookAt(0, 0, 0);
    scene.add(new T.HemisphereLight(0xe8e0ff, 0x1a0f2e, .6));
    const key = new T.DirectionalLight(0xffffff, .9); key.position.set(-3, 5, 6); scene.add(key);
    const rim2 = new T.PointLight(0x47d7ff, .9, 20); rim2.position.set(-4, -2, -1); scene.add(rim2);
    const front = new T.DirectionalLight(0xfff2dc, .45); front.position.set(0, -3.5, 7); scene.add(front);   // soft light from the player, a little below
    const glint = new T.PointLight(0xffd580, 0, 12); scene.add(glint);                 // a moving highlight while spinning
    const dice = [], scale = n > 1 ? .84 : 1, gap = 2.7;
    for (let i = 0; i < n; i++) {
      const d = buildDie(faces); d.mesh.scale.setScalar(scale);
      d.home = new T.Vector3((i - (n - 1) / 2) * gap, 0, 0); d.mesh.position.copy(d.home);
      d.idleAxis = new T.Vector3(Math.random() - .5, 1, Math.random() * .4).normalize();
      d.mesh.quaternion.setFromEuler(new T.Euler(Math.random() * 6, Math.random() * 6, 0));
      scene.add(d.mesh); dice.push(d);
    }
    const cap = document.createElement("div"); cap.className = "tray-cap"; cap.textContent = dice[0].name + (n > 1 ? ` × ${n},取大` : ""); el.appendChild(cap);
    // sparks that orbit during the spin and burst out on landing
    const NP = 90, sp = new Float32Array(NP * 3), seeds = Array.from({length: NP}, () => ({r: 1.6 + Math.random() * 1.2, a: Math.random() * 6.3, y: (Math.random() - .5) * 2.4, s: 2 + Math.random() * 3}));
    const pg = new T.BufferGeometry(); pg.setAttribute("position", new T.BufferAttribute(sp, 3));
    const pm = new T.PointsMaterial({size: .22, map: spriteTex(), transparent: true, depthWrite: false, blending: T.AdditiveBlending, opacity: 0, color: 0xffd98a});
    const sparks = new T.Points(pg, pm); scene.add(sparks);
    const landing = (d, v, i) => {                    // the rolled face turned straight at the player, number upright
      const f = d.rests.find(x => x.label === v) || d.rests[0];
      const toPlayer = new T.Vector3().subVectors(camera.position, dice[i].home);
      // d4: the rolled corner points straight at the player; its number sits by that tip on all three
      // faces around it, upright on the face below the tip
      return orient(f, toPlayer, new T.Vector3(0, 1, 0));
    };
    let raf = 0, dead = false, stage = el, nodes = [...el.childNodes];
    const draw = () => renderer.render(scene, camera);
    const setGlow = (d, k) => d.mats.forEach((m, j) => { if (j && m.emissiveMap) m.emissiveIntensity = k; });
    const placeSparks = (t, spread, fade) => { seeds.forEach((s, i) => { const a = s.a + t * s.s, r = s.r * spread;
      sp[i * 3] = Math.cos(a) * r; sp[i * 3 + 1] = s.y * spread * .6 + Math.sin(t * 3 + i) * .1; sp[i * 3 + 2] = Math.sin(a) * r * .6; });
      pg.attributes.position.needsUpdate = true; pm.opacity = fade; };
    const smooth = (a, b, x) => { const k = Math.min(1, Math.max(0, (x - a) / (b - a))); return k * k * (3 - 2 * k); };
    const reveal = vals => { const best = Math.max(...vals); stage.classList.add("revealed");
      if (best === faces) stage.classList.add("crit"); else if (best === 1) stage.classList.add("fumble"); };
    const handle = {
      key: `${faces}x${n}`, values: values || null,
      poses: () => dice.map(d => d.mesh.quaternion.toArray()),        // for tests: each die's orientation now
      dispose() { dead = true; cancelAnimationFrame(raf); renderer.dispose(); if (current === handle) current = null; },
      adopt(newEl) {                                   // the page redrew its form: carry the same scene over, mid-animation
        if (newEl === stage) return;
        newEl.className = stage.className; newEl.innerHTML = ""; nodes.forEach(nd => newEl.appendChild(nd)); stage = newEl;
      },
      rest(vals) {
        cancelAnimationFrame(raf); pm.opacity = 0; handle.values = vals;
        const best = Math.max(...vals);
        dice.forEach((d, i) => { d.mesh.position.copy(d.home); d.mesh.quaternion.copy(landing(d, vals[i], i));
          const dim = n > 1 && vals.indexOf(best) !== i;
          d.mesh.scale.setScalar(scale * (dim ? .86 : 1)); setGlow(d, dim ? .25 : 1.1); });
        draw();
      },
      idle() {
        const t0 = performance.now();
        const loop = now => { if (dead) return; const t = (now - t0) / 1000;
          dice.forEach((d, i) => { d.mesh.position.y = d.home.y + Math.sin(t * 1.8 + i) * .12;
            d.mesh.quaternion.premultiply(new T.Quaternion().setFromAxisAngle(d.idleAxis, .008)); setGlow(d, .45 + Math.sin(t * 2.4) * .15); });
          placeSparks(t * .3, 1, .35); draw(); raf = requestAnimationFrame(loop); };
        raf = requestAnimationFrame(loop);
      },
      /* One continuous motion, worked backwards from the result: each die turns about one axis by
         (a whole number of turns + exactly the angle between where it is now and its landing pose),
         speeding up then easing to a stop, so it starts where it was and stops on the rolled face;
         a tumble that is zero at both ends rides on top, and a damped rock settles it. */
      roll(vals) {
        cancelAnimationFrame(raf); handle.values = vals;
        if (REDUCED()) { handle.rest(vals); reveal(vals); return Promise.resolve(); }
        return new Promise(done => {
          const D = 2000, FLARE = 800, t0 = performance.now(), best = Math.max(...vals), win = vals.indexOf(best);
          const plan = dice.map((d, i) => {
            const qEnd = landing(d, vals[i], i), qStart = d.mesh.quaternion.clone();
            const delta = qEnd.clone().invert().multiply(qStart); if (delta.w < 0) { delta.x *= -1; delta.y *= -1; delta.z *= -1; delta.w *= -1; }
            const ang = 2 * Math.acos(Math.min(1, delta.w)), sn = Math.sqrt(Math.max(0, 1 - delta.w * delta.w));
            const axis = sn > 1e-4 ? new T.Vector3(delta.x / sn, delta.y / sn, delta.z / sn) : new T.Vector3(1, .4, .2).normalize();
            const tumble = new T.Vector3(Math.random() - .5, Math.random() - .5, Math.random() - .5).normalize();
            return {qEnd, axis, total: ang + Math.PI * 2 * (3 + i), tumble, tAmp: 1.1 + Math.random() * .6,
                    rock: new T.Vector3(1, (Math.random() - .5) * .6, 0).normalize(), y0: d.mesh.position.y - d.home.y};
          });
          let revealed = false;
          const loop = now => {
            if (dead) return done();
            const e = now - t0, t = Math.min(1, e / D);
            const g = Math.pow(1 - t, 3) * (1 + 3 * t);                     // 1 -> 0, still at both ends
            dice.forEach((d, i) => {
              const p = plan[i];
              const q = p.qEnd.clone()
                .multiply(new T.Quaternion().setFromAxisAngle(p.axis, p.total * g))
                .multiply(new T.Quaternion().setFromAxisAngle(p.tumble, p.tAmp * Math.pow(Math.sin(Math.PI * t), 2) * (1 - t)));
              const u = Math.max(0, (t - .8) / .2);                           // the landing rock
              q.premultiply(new T.Quaternion().setFromAxisAngle(p.rock, .14 * Math.exp(-4 * u) * Math.sin(3 * Math.PI * u) * (1 - u)));
              d.mesh.quaternion.copy(q);
              d.mesh.position.y = d.home.y + p.y0 * (1 - smooth(0, .25, t)) + .55 * Math.pow(Math.sin(Math.PI * Math.min(1, t * 1.15)), 2);
              const dim = n > 1 && i !== win ? smooth(.85, 1, t) : 0;
              const land = Math.max(0, (t - .9) / .1), pop = t < 1 ? .06 * Math.sin(Math.PI * land) : 0;
              const flareK = Math.max(0, (e - D) / FLARE);
              const flarePop = i === win && e > D ? .1 * Math.exp(-6 * flareK) * Math.cos(flareK * 12) : 0;
              d.mesh.scale.setScalar(scale * (1 - .14 * dim) * (1 + pop + flarePop));
              const glow = .55 + .55 * smooth(.7, 1, t);
              setGlow(d, i === win && e > D ? 1.1 + 2.4 * Math.exp(-5 * flareK) : glow * (1 - .75 * dim));
            });
            glint.intensity = 2.4 * Math.sin(Math.PI * Math.min(1, t * 1.1));
            glint.position.set(Math.cos(t * 28) * 3, 1.5, Math.sin(t * 28) * 3 + 2);
            const burst = e > D ? (e - D) / FLARE : 0;
            placeSparks(t * 4 + burst, 1 + burst * 2.5, e > D ? .9 * (1 - burst) : .9 * smooth(0, .12, t) * (1 - .6 * smooth(.6, .95, t)));
            draw();
            if (!revealed && e >= D) { revealed = true; reveal(vals); done(); }
            if (e < D + FLARE) raf = requestAnimationFrame(loop);
            else { pm.opacity = 0; draw(); }
          };
          raf = requestAnimationFrame(loop);
        });
      },
    };
    current = handle;
    if (values) { handle.rest(values); reveal(values); } else if (!rolling) handle.idle();
    return handle;
  }

  return {
    available: has3D,
    release() { if (current) current.dispose(); },
    current: () => current,
    name: f => kind(f).name,
    show(el, faces, n, values) {                     // reuse the scene on screen when it already shows this
      const same = current && current.key === `${faces}x${n}` &&
        JSON.stringify(current.values) === JSON.stringify(values || null);
      if (same) { current.adopt(el); return current; }
      return mount(el, faces, n, values, false);
    },
    roll(el, faces, n, values) {
      const here = current && current.key === `${faces}x${n}`;
      if (here) { current.adopt(el); return current.roll(values); }   // the die on screen rolls from where it is
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
                  E05: "🕊️ 和平日:无事发生", E06: "☄️ 火球 -3", E07: "🐕 饿狗:交 2 食物或 -3", E08: "🍗 盛宴预告:下回合在中心多抽 2 张手牌(中心没牌了就 health +3)"};
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
function emoji(g, ch, x, y, size, rot, alpha, flip) {   // flip: mirror it (animal emoji face left)
  g.save(); g.globalAlpha = alpha ?? 1; g.translate(x, y); if (rot) g.rotate(rot); if (flip) g.scale(-1, 1);
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

/* Three torn gashes, raked in one quick swipe: curved, fat in the middle and fine at the ends,
   dark wound with a raw red rim and a pale torn edge, a few drops, then a slow fade. */
function clawMarks(g, w, h, t, s) {
  if (!s.claw) s.claw = [-1, 0, 1].map(k => ({k, jag: Array.from({length: 26}, () => .75 + Math.random() * .5),
    drops: Array.from({length: 3}, () => ({at: .3 + Math.random() * .5, len: 0, v: 18 + Math.random() * 26}))}));
  const swipe = Math.min(1, Math.max(0, (t - .04) / .12)), fade = t < .7 ? 1 : 1 - (t - .7) / .3;
  if (swipe <= 0) return;
  const S = Math.min(w, h), cx = w * .5, cy = h * .48;
  s.claw.forEach((c, ci) => {
    const off = c.k * S * .17, p0 = [cx - S * .32 + off, cy - S * .36], p2 = [cx + S * .3 + off, cy + S * .4], p1 = [cx + off * .6 + S * .12, cy - S * .05];
    const lag = Math.min(1, Math.max(0, swipe * 1.25 - ci * .1)), N = 25, L = [], R = [];
    for (let i = 0; i <= N; i++) {
      const u = i / N * lag, a = 1 - u;
      const x = a * a * p0[0] + 2 * a * u * p1[0] + u * u * p2[0], y = a * a * p0[1] + 2 * a * u * p1[1] + u * u * p2[1];
      const dx = 2 * a * (p1[0] - p0[0]) + 2 * u * (p2[0] - p1[0]), dy = 2 * a * (p1[1] - p0[1]) + 2 * u * (p2[1] - p1[1]), dl = Math.hypot(dx, dy) || 1;
      const width = S * .045 * Math.pow(Math.sin(Math.PI * (i / N)), .7) * c.jag[i];
      L.push([x - dy / dl * width, y + dx / dl * width]); R.push([x + dy / dl * width * .6, y - dx / dl * width * .6]);
    }
    const poly = (pts, scale) => { g.beginPath(); pts.forEach(([x, y], i) => i ? g.lineTo(x, y) : g.moveTo(x, y)); };
    g.save(); g.globalAlpha = fade;
    g.shadowColor = "rgba(255,40,40,.8)"; g.shadowBlur = 10;
    poly(L.concat(R.reverse())); g.closePath(); g.fillStyle = "#7a0710"; g.fill();       // raw red rim
    g.shadowBlur = 0;
    const inner = L.map((pt, i) => { const r = R[R.length - 1 - i]; return [(pt[0] * 2 + r[0]) / 3, (pt[1] * 2 + r[1]) / 3]; });
    poly(inner.concat(R.slice().reverse().map((pt, i) => { const l = L[i]; return [(pt[0] * 2 + l[0]) / 3, (pt[1] * 2 + l[1]) / 3]; }).reverse()));
    g.closePath(); g.fillStyle = "#2a0004"; g.fill();                                     // the deep wound
    g.strokeStyle = "rgba(255,170,160,.55)"; g.lineWidth = 1; poly(L); g.stroke();         // pale torn edge
    if (lag > .98) c.drops.forEach(d => { const i = Math.round(d.at * N), [x, y] = L[Math.min(L.length - 1, i)];
      d.len = Math.min(S * .18, d.len + d.v / 60); g.fillStyle = "#6a0610";
      g.beginPath(); g.moveTo(x - 1.2, y); g.lineTo(x + 1.2, y); g.lineTo(x + .8, y + d.len); g.arc(x, y + d.len, 1.8, 0, Math.PI); g.lineTo(x - .8, y + d.len); g.fill(); });
    g.restore();
  });
  if (swipe < 1) {                                                                     // the bright edge of the swipe itself
    const x = w * (.2 + .6 * swipe), y = h * (.12 + .76 * swipe);
    const grd = g.createRadialGradient(x, y, 0, x, y, 22); grd.addColorStop(0, "rgba(255,240,230,.9)"); grd.addColorStop(1, "rgba(255,80,80,0)");
    g.fillStyle = grd; g.beginPath(); g.arc(x, y, 22, 0, 7); g.fill();
  }
}

/* A fiery blast where a fireball lands: a white flash, rolling fire puffs that swell and cool from
   yellow through orange and red into dark smoke that drifts up, and a scorch left behind.
   `e` = seconds since impact. */
function explosion(g, f, e, w, h, t) {
  g.fillStyle = `rgba(25,12,4,${.5 * envelope(t, .01, .25)})`; g.beginPath(); g.ellipse(f.tx, f.ty + 6, 20, 7, 0, 0, 7); g.fill();   // scorch
  if (e < .18) { const k = e / .18, r = 18 + 30 * k;
    const fl = g.createRadialGradient(f.tx, f.ty, 0, f.tx, f.ty, r); fl.addColorStop(0, `rgba(255,255,235,${1 - k})`); fl.addColorStop(.5, `rgba(255,220,120,${.8 * (1 - k)})`); fl.addColorStop(1, "rgba(255,140,40,0)");
    g.fillStyle = fl; g.beginPath(); g.arc(f.tx, f.ty, r, 0, 7); g.fill();
    g.fillStyle = `rgba(255,170,60,${.3 * (1 - k)})`; g.fillRect(0, 0, w, h); }
  const ramp = [[255, 244, 180], [255, 170, 40], [214, 70, 14], [70, 52, 44]];                                // fire cooling into smoke
  f.puffs.forEach(p => {
    const k = (e - p.delay) / 1.1; if (k < 0 || k > 1) return;
    const r = p.r * (.4 + 1.6 * ease(Math.min(1, k * 1.6))), x = f.tx + p.dx * (1 + k * 1.5), y = f.ty + p.dy + p.vy * k * 1.1;
    const c = Math.min(2.999, k * 3.4), i = Math.floor(c), m = c - i, col = ramp[i].map((v, j) => Math.round(v + (ramp[i + 1][j] - v) * m));
    const a = (k < .1 ? k / .1 : 1) * (1 - Math.pow(k, 2)) * (i >= 2 ? .75 : .95);
    const grd = g.createRadialGradient(x, y, 0, x, y, r); grd.addColorStop(0, `rgba(${col},${a})`); grd.addColorStop(.7, `rgba(${col},${a * .6})`); grd.addColorStop(1, `rgba(${col},0)`);
    g.fillStyle = grd; g.beginPath(); g.arc(x, y, r, 0, 7); g.fill();
  });
}

const FX = {
  E01(g, w, h, t, s, dt) {                               // wolves: claw slashes, then the pack bounds through
    g.fillStyle = `rgba(120,10,10,${.3 * envelope(t, .08, .35)})`; g.fillRect(0, 0, w, h);
    clawMarks(g, w, h, t, s);
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
    emoji(g, "🐒", mx, my + 8, 30, -ang * .4, 1, true);
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
    emoji(g, "🕊️", w * .2 + w * .6 * t, h * .7 - h * .55 * ease(t) + Math.sin(t * 22) * 4, 28, 0, k, true);
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
        for (let i = 0; i < 40; i++) { const a = rnd(Math.PI, 2 * Math.PI) + rnd(-.3, .3), v = rnd(70, 240);   // debris thrown up and out
          sparks.push({x: f.tx, y: f.ty, vx: Math.cos(a) * v, vy: Math.sin(a) * v, r: rnd(1.2, 3), life: rnd(.4, .9), max: .9, color: ["#fff2b0", "#ffb347", "#ff6a00"][i % 3]}); }
        f.puffs = Array.from({length: 8}, () => ({dx: rnd(-14, 14), dy: rnd(-12, 4), r: rnd(9, 16), vy: rnd(-34, -14), delay: rnd(0, .08)}));
      }
      if (f.hit) explosion(g, f, (t - f.hitAt) * FX_MS / 1000, w, h, t);
    });
    drawParts(g, sparks, dt, 320);
  },
  E07(g, w, h, t, s, dt) {                               // hungry dogs: dogs charge in, food flies off
    g.fillStyle = `rgba(120,60,20,${.12 * envelope(t, .1, .3)})`; g.fillRect(0, 0, w, h);
    const dust = particles(s, "d", 0, () => ({}));
    drawParts(g, dust, dt, 0);                                                          // dust first, so it trails behind the dogs
    // x along the way: dash in from the right, stop at the food, then on out to the left (always facing left)
    const along = t < .4 ? ease(t / .4) * .5 : t < .58 ? .5 : .5 + .5 * Math.pow((t - .58) / .42, 1.6);
    if (t < .5) emoji(g, "🍖", w * .45, h * .58, 20, 0, 1);
    [0, 1].forEach(i => { const x = (w + 40) - (w + 110) * along + i * 34, y = h * (.42 + i * .2) - (t > .4 && t < .58 ? 0 : Math.abs(Math.sin(t * 40 + i)) * 6);
      g.save(); g.shadowColor = "rgba(0,0,0,.75)"; g.shadowBlur = 6; g.shadowOffsetY = 2;          // a dark halo keeps them readable on any ground
      emoji(g, "🐕", x, y, 34, 0);
      if (i === 0 && t >= .5) emoji(g, "🍖", x - 19, y + 7, 18, -.4);                     // carried off in its mouth
      g.restore();
      if (t < .4 || t > .58) if (Math.random() < .35) dust.push({x: x + 18, y: y + 14, vx: rnd(10, 40), vy: rnd(-12, 0), r: rnd(1.5, 3), life: .45, max: .45, color: "#b58b5a", a: .35, grow: 1.2}); });
  },
  E08(g, w, h, t, s, dt) {                               // feast: a golden banquet table laid out under falling light
    const k = envelope(t, .12, .2), S = Math.min(w, h);
    const glow = g.createRadialGradient(w / 2, h * .45, 0, w / 2, h * .45, Math.max(w, h) * .8);
    glow.addColorStop(0, `rgba(255,214,120,${.45 * k})`); glow.addColorStop(1, "rgba(255,180,60,0)");
    g.fillStyle = glow; g.fillRect(0, 0, w, h);
    g.save(); g.globalCompositeOperation = "lighter";                                     // shafts of light from above
    for (let i = 0; i < 4; i++) { const x = w * (.2 + .2 * i) + Math.sin(t * 2 + i) * 6;
      const sh = g.createLinearGradient(x, 0, x, h); sh.addColorStop(0, `rgba(255,225,150,${.28 * k})`); sh.addColorStop(1, "rgba(255,225,150,0)");
      g.fillStyle = sh; g.beginPath(); g.moveTo(x - 6, 0); g.lineTo(x + 6, 0); g.lineTo(x + 22, h); g.lineTo(x - 22, h); g.fill(); }
    g.restore();
    // the table: a cloth-covered top in perspective, gold trim, legs
    const rise = ease(Math.min(1, t / .25)), ty = h * .5 + (1 - rise) * 20;
    const tl = w * .16, tr = w * .84, bl = w * .06, br = w * .94, top = ty, bot = ty + S * .22;
    g.globalAlpha = k;
    g.fillStyle = "#3b2414"; [[bl + 10, bot], [br - 16, bot]].forEach(([x, y]) => g.fillRect(x, y, 6, h - y));
    const cloth = g.createLinearGradient(0, top, 0, bot); cloth.addColorStop(0, "#fff6e0"); cloth.addColorStop(1, "#e6d2a6");
    g.fillStyle = cloth; g.beginPath(); g.moveTo(tl, top); g.lineTo(tr, top); g.lineTo(br, bot); g.lineTo(bl, bot); g.closePath(); g.fill();
    g.fillStyle = "#d9a83e"; g.beginPath(); g.moveTo(bl, bot); g.lineTo(br, bot); g.lineTo(br - 4, bot + 8); g.lineTo(bl + 4, bot + 8); g.fill();   // gold hem
    g.strokeStyle = "rgba(160,110,20,.7)"; g.lineWidth = 1.5; g.beginPath(); g.moveTo(tl, top); g.lineTo(tr, top); g.stroke();
    // gold plates, then the food lands on them one by one
    const dishes = ["🍗", "🥩", "🍉", "🍎", "🍖"];
    dishes.forEach((ch, i) => {
      const u = (i + .5) / dishes.length, x = bl + (br - bl) * u * .9 + (br - bl) * .05, y = top + (bot - top) * .55;
      const pg = g.createRadialGradient(x - 3, y - 2, 1, x, y, S * .07); pg.addColorStop(0, "#fff1b0"); pg.addColorStop(.6, "#e0ac3c"); pg.addColorStop(1, "#8a5d12");
      g.fillStyle = pg; g.beginPath(); g.ellipse(x, y, S * .075, S * .03, 0, 0, 7); g.fill();
      const land = (t - .18 - i * .07) / .2; if (land < 0) return;
      const dropY = y - 6 - (1 - ease(Math.min(1, land))) * S * .5, bounce = land > 1 && land < 1.4 ? Math.sin((land - 1) / .4 * Math.PI) * 3 : 0;
      emoji(g, ch, x, dropY - bounce, S * .13, 0, k);
    });
    // candles with flickering flames
    [.32, .68].forEach((u, ci) => { const x = tl + (tr - tl) * u, y = top - 2;
      g.fillStyle = "#f5ecd6"; g.fillRect(x - 2.5, y - S * .14, 5, S * .14);
      const fl = 1 + Math.sin(t * 40 + ci * 3) * .15 + Math.sin(t * 23) * .1;
      const fg = g.createRadialGradient(x, y - S * .16, 0, x, y - S * .16, 10 * fl); fg.addColorStop(0, "#fffbe0"); fg.addColorStop(.4, "#ffc34a"); fg.addColorStop(1, "rgba(255,120,0,0)");
      g.fillStyle = fg; g.beginPath(); g.ellipse(x, y - S * .17, 4 * fl, 8 * fl, 0, 0, 7); g.fill(); });
    g.globalAlpha = 1;
    // glints: four-point stars that twinkle, and gold dust drifting up
    const stars = particles(s, "st", 14, () => ({x: rnd(0, w), y: rnd(0, h * .8), ph: rnd(0, 6), sz: rnd(3, 7)}));
    stars.forEach(p => { const tw = Math.max(0, Math.sin(t * 9 + p.ph)) * k; if (tw < .05) return;
      g.fillStyle = `rgba(255,240,190,${tw})`; g.beginPath(); const r = p.sz * tw;
      g.moveTo(p.x, p.y - r); g.quadraticCurveTo(p.x, p.y, p.x + r, p.y); g.quadraticCurveTo(p.x, p.y, p.x, p.y + r);
      g.quadraticCurveTo(p.x, p.y, p.x - r, p.y); g.quadraticCurveTo(p.x, p.y, p.x, p.y - r); g.fill(); });
    const dust = particles(s, "gd", 30, () => ({x: rnd(0, w), y: rnd(h * .3, h), vx: rnd(-6, 6), vy: rnd(-26, -10), r: rnd(.8, 2), color: "#ffd77a", life: 9, max: 9, a: .8}));
    dust.forEach(p => { if (p.y < 0) { p.y = h; } });
    drawParts(g, dust, dt, 0);
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
