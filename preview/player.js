/* Плеер превью: те же слои и ключи, что в .keyshape.
   Семантика Keyshape: позиция группы = пивот, scale/rotate вокруг неё,
   контент внутри нарисован со сдвигом -пивот. */
(function () {
  "use strict";

  var qs = new URLSearchParams(location.search);
  var STILL = qs.has("still");
  var ONLY = qs.get("only");
  var T0 = qs.has("t") ? parseFloat(qs.get("t")) : 0;
  var LOOP = window.ANIM.loop;

  /* ---- cubic-bezier ---- */
  function bezier(x1, y1, x2, y2) {
    var cx = 3 * x1, bx = 3 * (x2 - x1) - cx, ax = 1 - cx - bx;
    var cy = 3 * y1, by = 3 * (y2 - y1) - cy, ay = 1 - cy - by;
    function sx(t) { return ((ax * t + bx) * t + cx) * t; }
    function sy(t) { return ((ay * t + by) * t + cy) * t; }
    function dsx(t) { return (3 * ax * t + 2 * bx) * t + cx; }
    return function (x) {
      if (x <= 0) return 0;
      if (x >= 1) return 1;
      var t = x, i, d, dd;
      for (i = 0; i < 8; i++) {
        d = sx(t) - x;
        if (Math.abs(d) < 1e-5) return sy(t);
        dd = dsx(t);
        if (Math.abs(dd) < 1e-6) break;
        t -= d / dd;
        if (t < 0 || t > 1) break;
      }
      var lo = 0, hi = 1;
      t = x;
      for (i = 0; i < 30; i++) {
        d = sx(t);
        if (Math.abs(d - x) < 1e-5) break;
        if (d < x) lo = t; else hi = t;
        t = (lo + hi) / 2;
      }
      return sy(t);
    };
  }

  function evalChannel(ch, t) {
    var k = ch.keys, i, t0, v0, t1, v1, p, e;
    if (t <= k[0][0]) return k[0][1];
    for (i = 0; i < k.length - 1; i++) {
      t0 = k[i][0]; v0 = k[i][1]; t1 = k[i + 1][0]; v1 = k[i + 1][1];
      if (t <= t1) {
        p = t1 === t0 ? 1 : (t - t0) / (t1 - t0);
        e = ch._fn[i](p);
        if (typeof v0 === "number") return v0 + (v1 - v0) * e;
        return [v0[0] + (v1[0] - v0[0]) * e, v0[1] + (v1[1] - v0[1]) * e];
      }
    }
    return k[k.length - 1][1];
  }

  /* ---- построение сцены ---- */
  var stage = document.getElementById("stage");
  var scenes = [];

  window.ANIM.frames.forEach(function (fr) {
    if (ONLY && fr.key !== ONLY) return;
    var card = document.createElement("div");
    card.className = "card" + (fr.key === "9x16" ? " narrow" : "");
    var h2 = document.createElement("h2");
    h2.innerHTML = fr.title + "<span>" + fr.w + "×" + fr.h + "</span>";
    card.appendChild(h2);
    var frame = document.createElement("div");
    frame.className = "frame";
    frame.innerHTML = fr.svg;
    card.appendChild(frame);
    stage.appendChild(card);

    var items = [];
    fr.layers.forEach(function (ly) {
      if (ly.static) return;
      var el = frame.querySelector('[id="' + ly.id + '"]');
      if (!el) { console.warn("слой не найден", ly.id); return; }
      ly.channels.forEach(function (ch) {
        ch._fn = ch.ease.map(function (e) { return bezier(e[0], e[1], e[2], e[3]); });
      });
      items.push({ el: el, layer: ly });
    });
    scenes.push({ frame: fr, items: items });
  });

  function apply(t) {
    scenes.forEach(function (sc) {
      sc.items.forEach(function (it) {
        var ly = it.layer;
        var pos = ly.pivot, sc2 = [1, 1], rot = 0, op = 1;
        for (var i = 0; i < ly.channels.length; i++) {
          var ch = ly.channels[i], v = evalChannel(ch, t);
          if (ch.kind === "motion") pos = v;
          else if (ch.kind === "scale") sc2 = v;
          else if (ch.kind === "rotate") rot = v;
          else if (ch.kind === "opacity") op = v;
        }
        it.el.setAttribute("transform",
          "translate(" + pos[0].toFixed(3) + "," + pos[1].toFixed(3) + ")" +
          (rot ? " rotate(" + rot.toFixed(3) + ")" : "") +
          " scale(" + sc2[0].toFixed(5) + "," + sc2[1].toFixed(5) + ")");
        if (op !== 1) it.el.setAttribute("opacity", op.toFixed(4));
        else it.el.removeAttribute("opacity");
      });
    });
  }

  /* ---- управление ---- */
  var t = ((T0 % LOOP) + LOOP) % LOOP;
  var playing = !STILL;
  var speed = 1;
  var speeds = [1, 0.5, 0.25, 2];
  var last = 0;

  apply(t);

  if (STILL) {
    document.body.classList.add("still");
    return;
  }

  var playBtn = document.getElementById("play");
  var scrub = document.getElementById("scrub");
  var timeEl = document.getElementById("time");
  var speedBtn = document.getElementById("speed");
  scrub.max = LOOP;

  function ui() {
    scrub.value = t;
    timeEl.textContent = t.toFixed(2) + " s";
    playBtn.textContent = playing ? "Пауза" : "Играть";
  }
  ui();

  playBtn.onclick = function () { playing = !playing; last = 0; ui(); };
  speedBtn.onclick = function () {
    speed = speeds[(speeds.indexOf(speed) + 1) % speeds.length];
    speedBtn.textContent = speed + "×";
  };
  scrub.oninput = function () { t = parseFloat(scrub.value); playing = false; ui(); };

  function loop(ts) {
    if (!last) last = ts;
    var dt = (ts - last) / 1000;
    last = ts;
    if (playing) {
      t = (t + dt * speed) % LOOP;
      ui();
    }
    apply(t);
    requestAnimationFrame(loop);
  }
  requestAnimationFrame(loop);
})();
