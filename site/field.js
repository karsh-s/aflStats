/* Margin — animated AFL field hero
   8 Hawthorn (brown/gold centred stripes) v 8 Essendon (black + red sash). The
   pack drifts end-to-end with the play; movement is slow and a touch sporadic.
   Players hold the ball for a beat, then fire a short straight pass — whoever
   receives pops up much bigger for a moment. */
(function () {
  "use strict";
  var canvas = document.getElementById("fieldCanvas");
  if (!canvas) return;
  var ctx = canvas.getContext("2d");
  var reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  var LINE = "rgba(20,19,15,.32)";
  var BALL = "#e01b1b", ACCENT = "#3b3bff";              // red ball
  var HAWK_BROWN = "#4a2509", HAWK_GOLD = "#f2c200";     // Hawthorn
  var BOMB_BLACK = "#111111", BOMB_RED = "#d6122e";      // Essendon

  var W, H, cx, cy, rx, ry, DPR, R, playX = 0;
  var players = [], ball, last = 0, trail = [];

  var TEAMS = [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,        // 12 Hawks
               1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1];      // 12 Bombers
  var N = TEAMS.length;
  var POP = 2.0;                                          // size when receiving

  function rand(a, b) { return a + Math.random() * (b - a); }

  function resize() {
    DPR = Math.min(window.devicePixelRatio || 1, 2);
    var rect = canvas.getBoundingClientRect();
    W = rect.width; H = rect.height;
    canvas.width = Math.round(W * DPR);
    canvas.height = Math.round(H * DPR);
    ctx.setTransform(DPR, 0, 0, DPR, 0, 0);
    cx = W / 2; cy = H / 2;
    rx = Math.min(W * 0.40, 560);
    ry = Math.min(H * 0.40, rx * 0.74);
    R = Math.max(10, Math.min(rx, ry) * 0.05);
  }

  function newOffset(p) {
    p.ox = rand(-rx * 0.52, rx * 0.52);
    p.oy = rand(-ry * 0.84, ry * 0.84);
  }

  function clampEllipse(p, pad) {
    var nx = (p.x - cx) / (rx - pad), ny = (p.y - cy) / (ry - pad);
    var d = nx * nx + ny * ny;
    if (d > 1) {
      var s = 1 / Math.sqrt(d);
      p.x = cx + (p.x - cx) * s; p.y = cy + (p.y - cy) * s;
      p.vx *= -0.25; p.vy *= -0.25;
    }
  }

  function init() {
    players = TEAMS.map(function (team) {
      var a = Math.random() * Math.PI * 2, r = Math.sqrt(Math.random()) * 0.8;
      var p = { x: cx + Math.cos(a) * rx * r, y: cy + Math.sin(a) * ry * r,
                vx: rand(-20, 20), vy: rand(-20, 20), team: team, scale: 1 };
      newOffset(p); return p;
    });
    ball = { holder: 0, state: "held", t: 0, hold: rand(1.6, 2.8),
             x: players[0].x, y: players[0].y, fx: 0, fy: 0, to: 0, dur: 1 };
    players[0].scale = POP; playX = ball.x; trail = [];
  }

  function pickTarget(from) {                // short pass, team-mate biased
    var fp = players[from], best = -1, bestScore = 1e9;
    for (var k = 0; k < 7; k++) {
      var j = (Math.random() * N) | 0;
      if (j === from) continue;
      var d = Math.hypot(players[j].x - fp.x, players[j].y - fp.y);
      var tm = players[j].team === fp.team ? 0.8 : 1.35;
      var score = d * tm * rand(0.85, 1.2);
      if (score < bestScore) { bestScore = score; best = j; }
    }
    return best < 0 ? (from + 1) % N : best;
  }

  function step(dt) {
    // the play drifts toward the ball so the pack shifts end to end with it
    playX += (ball.x - playX) * Math.min(1, dt * 1.7);

    for (var i = 0; i < N; i++) {
      var p = players[i];
      // the carrier stays big the whole time it holds; others ease back to 1,
      // so a player only shrinks once it has given the ball away.
      if (i !== ball.holder) p.scale += (1 - p.scale) * Math.min(1, dt * 2.4);
      // steer toward a play-relative spot (slow)
      p.vx += (playX + p.ox - p.x) * 2.0 * dt;
      p.vy += (cy + p.oy - p.y) * 2.0 * dt;
      // gentle sporadic movement
      p.vx += rand(-1, 1) * 13; p.vy += rand(-1, 1) * 13;
      if (Math.random() < 0.01) newOffset(p);
      // separation
      for (var j = i + 1; j < N; j++) {
        var q = players[j], sx = p.x - q.x, sy = p.y - q.y, sd = Math.hypot(sx, sy);
        var min = R * 3.7;                                  // spread players out more
        if (sd < min && sd > 0.001) {
          var f = (min - sd) / min * 38 * dt; sx /= sd; sy /= sd;
          p.vx += sx * f; p.vy += sy * f; q.vx -= sx * f; q.vy -= sy * f;
        }
      }
      p.vx *= 0.9; p.vy *= 0.9;
      var sp = Math.hypot(p.vx, p.vy), max = 62;           // slow
      if (sp > max) { p.vx = p.vx / sp * max; p.vy = p.vy / sp * max; }
      p.x += p.vx * dt; p.y += p.vy * dt;
      clampEllipse(p, R + 4);
    }

    // ball — hold long, then a quick straight pass
    var h = players[ball.holder];
    if (ball.state === "held") {
      ball.x = h.x; ball.y = h.y; ball.t += dt;
      if (ball.t >= ball.hold) {
        ball.to = pickTarget(ball.holder);
        ball.fx = ball.x; ball.fy = ball.y;
        var d = Math.hypot(players[ball.to].x - ball.fx, players[ball.to].y - ball.fy);
        ball.dur = Math.max(0.22, Math.min(0.5, d / 850));
        ball.state = "pass"; ball.t = 0;
      }
    } else {
      ball.t += dt / ball.dur;
      var tt = Math.min(ball.t, 1);
      var e = tt < 0.5 ? 2 * tt * tt : 1 - Math.pow(-2 * tt + 2, 2) / 2;
      ball.x = ball.fx + (players[ball.to].x - ball.fx) * e;   // straight line
      ball.y = ball.fy + (players[ball.to].y - ball.fy) * e;
      if (ball.t >= 1) {
        ball.holder = ball.to; ball.state = "held"; ball.t = 0; ball.hold = rand(1.6, 2.8);
        players[ball.to].scale = POP;                          // receiver pops big
      }
    }
    trail.push({ x: ball.x, y: ball.y });
    if (trail.length > 12) trail.shift();
  }

  function ellipsePath(erx, ery) { ctx.beginPath(); ctx.ellipse(cx, cy, erx, ery, 0, 0, Math.PI * 2); }

  function drawField() {
    ctx.lineWidth = 1.4; ctx.strokeStyle = LINE;
    ellipsePath(rx, ry); ctx.stroke();
    ellipsePath(rx - 10, ry - 8); ctx.globalAlpha = 0.5; ctx.stroke(); ctx.globalAlpha = 1;

    var c = Math.min(rx, ry) * 0.13;
    ctx.strokeRect(cx - c, cy - c, c * 2, c * 2);
    ctx.beginPath(); ctx.arc(cx, cy, c * 1.7, 0, Math.PI * 2); ctx.stroke();
    ctx.beginPath(); ctx.arc(cx, cy, 4, 0, Math.PI * 2); ctx.fillStyle = LINE; ctx.fill();

    ctx.save(); ellipsePath(rx, ry); ctx.clip();
    ctx.lineWidth = 1.4; ctx.strokeStyle = LINE;
    var rA = rx * 0.60;
    ctx.beginPath(); ctx.arc(cx - rx, cy, rA, -Math.PI / 2, Math.PI / 2); ctx.stroke();
    ctx.beginPath(); ctx.arc(cx + rx, cy, rA, Math.PI / 2, Math.PI * 1.5); ctx.stroke();
    ctx.restore();

    ctx.lineWidth = 2.4; ctx.lineCap = "round";
    var goalLen = Math.min(rx, ry) * 0.34, behindLen = goalLen * 0.62;
    [-1, 1].forEach(function (s) {
      var gx = cx + s * rx;
      [[-0.10, behindLen], [-0.035, goalLen], [0.035, goalLen], [0.10, behindLen]]
        .forEach(function (post) {
          var py = cy + ry * post[0];
          ctx.beginPath(); ctx.moveTo(gx, py); ctx.lineTo(gx - s * post[1], py); ctx.stroke();
        });
    });
    ctx.lineCap = "butt";
  }

  function drawGuernsey(p) {
    var rr = R * p.scale;
    ctx.save();
    ctx.beginPath(); ctx.arc(p.x, p.y, rr, 0, Math.PI * 2); ctx.clip();
    if (p.team === 0) {                       // Hawthorn — centred brown/gold stripes
      ctx.fillStyle = HAWK_BROWN; ctx.fillRect(p.x - rr, p.y - rr, rr * 2, rr * 2);
      ctx.fillStyle = HAWK_GOLD;
      var sw = rr * 0.44;
      for (var n = -2; n <= 2; n++) ctx.fillRect(p.x + n * sw * 2 - sw / 2, p.y - rr, sw, rr * 2);
    } else {                                  // Essendon — black with red sash
      ctx.fillStyle = BOMB_BLACK; ctx.fillRect(p.x - rr, p.y - rr, rr * 2, rr * 2);
      ctx.save(); ctx.translate(p.x, p.y); ctx.rotate(-Math.PI / 4);
      ctx.fillStyle = BOMB_RED; ctx.fillRect(-rr * 1.7, -rr * 0.4, rr * 3.4, rr * 0.8);
      ctx.restore();
    }
    ctx.restore();
    ctx.beginPath(); ctx.arc(p.x, p.y, rr, 0, Math.PI * 2);
    ctx.lineWidth = 1.6; ctx.strokeStyle = "rgba(20,19,15,.6)"; ctx.stroke();
  }

  function draw() {
    ctx.clearRect(0, 0, W, H);
    drawField();
    for (var i = 0; i < trail.length; i++) {
      var a = i / trail.length;
      ctx.beginPath(); ctx.arc(trail[i].x, trail[i].y, 2.2 * a + 0.6, 0, Math.PI * 2);
      ctx.fillStyle = "rgba(224,27,27," + (a * 0.45) + ")"; ctx.fill();
    }
    for (var k = 0; k < N; k++) drawGuernsey(players[k]);

    ctx.save(); ctx.translate(ball.x, ball.y);
    ctx.beginPath(); ctx.ellipse(0, 0, R * 0.6, R * 0.44, 0, 0, Math.PI * 2);
    ctx.fillStyle = BALL; ctx.fill();
    ctx.lineWidth = 1; ctx.strokeStyle = "rgba(255,255,255,.8)";
    ctx.beginPath(); ctx.moveTo(-R * 0.45, 0); ctx.lineTo(R * 0.45, 0); ctx.stroke();
    ctx.restore();
  }

  function frame(ts) {
    var t = ts / 1000;
    var dt = last ? Math.min(t - last, 0.05) : 0.016; last = t;
    step(dt); draw();
    requestAnimationFrame(frame);
  }

  function start() {
    resize(); init();
    if (reduce) { step(0.016); draw(); return; }
    requestAnimationFrame(frame);
  }

  var rt;
  window.addEventListener("resize", function () {
    clearTimeout(rt); rt = setTimeout(function () { resize(); init(); if (reduce) { step(0.016); draw(); } }, 150);
  });

  start();

  // ---- caption rotator ----
  var rotator = document.getElementById("rotator");
  if (rotator && !reduce) {
    var phrases = ["Calibrated Predictions", "Every Disposal Modelled",
                   "Win Probabilities", "Honest Edges"];
    var idx = 0;
    setInterval(function () {
      rotator.classList.add("swap");
      setTimeout(function () {
        idx = (idx + 1) % phrases.length;
        rotator.textContent = phrases[idx];
        rotator.classList.remove("swap");
      }, 500);
    }, 3000);
  }
})();
