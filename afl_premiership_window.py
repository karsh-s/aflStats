#!/usr/bin/env python3
"""
AFL Premiership Window Dashboard
=================================
Run:  python3 afl_premiership_window.py
Then open: http://localhost:8080

Fetches live data from api.squiggle.com.au (no API key needed).
"""

import http.server
import json
import urllib.request
import urllib.parse
import threading
import webbrowser
import sys

# ─── HTML / CSS / JS ──────────────────────────────────────────────────────────

HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AFL Premiership Window</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Bebas+Neue&family=DM+Sans:wght@300;400;500;600&display=swap');

  :root {
    --bg:        #0a0d12;
    --surface:   #111620;
    --card:      #161c2a;
    --border:    #1e2840;
    --accent:    #f5a623;
    --accent2:   #e8453c;
    --green:     #2ecc71;
    --text:      #e8eaf0;
    --muted:     #6b7a99;
    --win:       #2ecc71;
    --loss:      #e8453c;
    --draw:      #f5a623;
    --top8:      rgba(245,166,35,0.12);
    --radius:    12px;
  }

  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

  body {
    background: var(--bg);
    color: var(--text);
    font-family: 'DM Sans', sans-serif;
    min-height: 100vh;
    overflow-x: hidden;
  }

  /* ── HEADER ── */
  header {
    background: linear-gradient(135deg, #0d1220 0%, #111a30 100%);
    border-bottom: 1px solid var(--border);
    padding: 18px 32px;
    display: flex;
    align-items: center;
    gap: 16px;
    position: sticky;
    top: 0;
    z-index: 100;
    backdrop-filter: blur(10px);
  }
  .logo {
    font-family: 'Bebas Neue', sans-serif;
    font-size: 2rem;
    letter-spacing: 3px;
    background: linear-gradient(90deg, var(--accent), #ff6b35);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
  }
  .subtitle {
    font-size: 0.75rem;
    color: var(--muted);
    letter-spacing: 2px;
    text-transform: uppercase;
  }
  #season-badge {
    margin-left: auto;
    background: var(--border);
    border: 1px solid #2a3550;
    border-radius: 6px;
    padding: 4px 12px;
    font-size: 0.8rem;
    color: var(--accent);
    font-weight: 600;
    letter-spacing: 1px;
  }
  #loading-bar {
    position: fixed;
    top: 0; left: 0;
    height: 3px;
    width: 0%;
    background: linear-gradient(90deg, var(--accent), #ff6b35);
    transition: width 0.3s ease;
    z-index: 999;
  }

  /* ── MAIN LAYOUT ── */
  .container {
    max-width: 1400px;
    margin: 0 auto;
    padding: 32px 24px;
    display: grid;
    grid-template-columns: 1fr 380px;
    gap: 24px;
    align-items: start;
  }

  /* ── CHART SECTION ── */
  .chart-section { display: flex; flex-direction: column; gap: 20px; }

  .section-title {
    font-family: 'Bebas Neue', sans-serif;
    font-size: 1.4rem;
    letter-spacing: 2px;
    color: var(--accent);
    display: flex;
    align-items: center;
    gap: 10px;
  }
  .section-title::after {
    content: '';
    flex: 1;
    height: 1px;
    background: var(--border);
  }

  /* ── PREMIERSHIP WINDOW CHART ── */
  #chart-wrap {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 28px 24px 20px;
    overflow: hidden;
  }
  #chart-canvas {
    width: 100%;
    cursor: pointer;
  }

  /* ── LEGEND ── */
  .legend {
    display: flex;
    gap: 20px;
    flex-wrap: wrap;
    padding: 8px 0 0;
  }
  .legend-item {
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: 0.75rem;
    color: var(--muted);
  }
  .legend-dot {
    width: 10px; height: 10px;
    border-radius: 50%;
  }

  /* ── LADDER TABLE ── */
  .ladder-section { display: flex; flex-direction: column; gap: 20px; }

  .ladder-card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    overflow: hidden;
  }

  .ladder-header {
    padding: 14px 18px;
    background: var(--card);
    border-bottom: 1px solid var(--border);
    display: grid;
    grid-template-columns: 30px 1fr 40px 40px 40px 50px;
    gap: 4px;
    font-size: 0.65rem;
    text-transform: uppercase;
    letter-spacing: 1.5px;
    color: var(--muted);
    font-weight: 600;
  }

  .ladder-row {
    padding: 10px 18px;
    display: grid;
    grid-template-columns: 30px 1fr 40px 40px 40px 50px;
    gap: 4px;
    align-items: center;
    border-bottom: 1px solid rgba(30,40,64,0.5);
    cursor: pointer;
    transition: background 0.15s, transform 0.15s;
    font-size: 0.85rem;
  }
  .ladder-row:last-child { border-bottom: none; }
  .ladder-row:hover { background: rgba(245,166,35,0.06); }
  .ladder-row.selected {
    background: rgba(245,166,35,0.12) !important;
    border-left: 3px solid var(--accent);
  }
  .ladder-row.top8 { background: var(--top8); }

  .pos-num {
    font-family: 'Bebas Neue', sans-serif;
    font-size: 1rem;
    color: var(--muted);
    text-align: center;
  }
  .pos-num.top4 { color: var(--accent); }
  .pos-num.top8 { color: #7ec8e3; }

  .team-name-cell {
    font-weight: 500;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .pct-cell {
    font-family: 'DM Sans', sans-serif;
    font-size: 0.8rem;
    color: var(--muted);
    text-align: right;
  }
  .pts-cell {
    font-weight: 700;
    font-size: 0.9rem;
    text-align: right;
    color: var(--accent);
  }
  .num-cell { text-align: center; color: var(--muted); font-size: 0.8rem; }

  .top8-divider {
    height: 2px;
    background: linear-gradient(90deg, var(--accent) 0%, transparent 100%);
    opacity: 0.4;
  }

  /* ── TEAM DETAIL PANEL ── */
  #detail-panel {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    overflow: hidden;
    animation: slideIn 0.25s ease;
    display: none;
  }
  @keyframes slideIn {
    from { opacity: 0; transform: translateY(-8px); }
    to   { opacity: 1; transform: translateY(0); }
  }
  .detail-hero {
    padding: 24px;
    background: linear-gradient(135deg, var(--card), var(--border));
    border-bottom: 1px solid var(--border);
    text-align: center;
  }
  .detail-team-name {
    font-family: 'Bebas Neue', sans-serif;
    font-size: 1.8rem;
    letter-spacing: 3px;
    line-height: 1.1;
  }
  .detail-pos {
    font-size: 0.75rem;
    color: var(--muted);
    letter-spacing: 2px;
    text-transform: uppercase;
    margin-top: 4px;
  }
  .detail-stats {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 1px;
    background: var(--border);
    border-bottom: 1px solid var(--border);
  }
  .stat-box {
    background: var(--card);
    padding: 16px 10px;
    text-align: center;
  }
  .stat-val {
    font-family: 'Bebas Neue', sans-serif;
    font-size: 1.6rem;
    letter-spacing: 1px;
    line-height: 1;
  }
  .stat-lbl {
    font-size: 0.65rem;
    text-transform: uppercase;
    letter-spacing: 1.5px;
    color: var(--muted);
    margin-top: 3px;
  }

  .last-result {
    padding: 20px 24px;
  }
  .last-result h3 {
    font-size: 0.7rem;
    text-transform: uppercase;
    letter-spacing: 2px;
    color: var(--muted);
    margin-bottom: 12px;
  }
  .result-card {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 16px;
  }
  .result-teams {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 8px;
    margin-bottom: 10px;
  }
  .result-team { font-weight: 600; font-size: 0.9rem; }
  .result-score { font-family: 'Bebas Neue', sans-serif; font-size: 1.3rem; }
  .vs-badge {
    font-size: 0.7rem;
    color: var(--muted);
    background: var(--border);
    border-radius: 4px;
    padding: 2px 6px;
  }
  .result-meta {
    display: flex;
    justify-content: space-between;
    font-size: 0.72rem;
    color: var(--muted);
  }
  .win-badge, .loss-badge, .draw-badge {
    display: inline-block;
    padding: 2px 10px;
    border-radius: 4px;
    font-size: 0.7rem;
    font-weight: 700;
    letter-spacing: 1px;
    text-transform: uppercase;
  }
  .win-badge  { background: rgba(46,204,113,0.15); color: var(--win); }
  .loss-badge { background: rgba(232,69,60,0.15);  color: var(--loss); }
  .draw-badge { background: rgba(245,166,35,0.15); color: var(--draw); }

  /* ── WINDOW METER ── */
  .window-meter {
    padding: 16px 24px 20px;
    border-top: 1px solid var(--border);
  }
  .window-meter h3 {
    font-size: 0.7rem;
    text-transform: uppercase;
    letter-spacing: 2px;
    color: var(--muted);
    margin-bottom: 12px;
  }
  .meter-bar-wrap {
    background: var(--border);
    border-radius: 6px;
    height: 10px;
    overflow: hidden;
    margin-bottom: 6px;
  }
  .meter-bar {
    height: 100%;
    border-radius: 6px;
    transition: width 0.6s cubic-bezier(0.34,1.56,0.64,1);
    background: linear-gradient(90deg, var(--accent2), var(--accent));
  }
  .meter-labels {
    display: flex;
    justify-content: space-between;
    font-size: 0.7rem;
    color: var(--muted);
  }
  .window-desc {
    margin-top: 10px;
    font-size: 0.8rem;
    color: var(--text);
    line-height: 1.5;
    background: var(--card);
    border-radius: 6px;
    padding: 10px 12px;
    border-left: 3px solid var(--accent);
  }

  /* ── FORM DOTS ── */
  .form-dots {
    padding: 14px 24px;
    border-top: 1px solid var(--border);
  }
  .form-dots h3 {
    font-size: 0.7rem;
    text-transform: uppercase;
    letter-spacing: 2px;
    color: var(--muted);
    margin-bottom: 10px;
  }
  .dots-row { display: flex; gap: 6px; align-items: center; }
  .dot {
    width: 26px; height: 26px;
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 0.65rem;
    font-weight: 700;
    letter-spacing: 0;
  }
  .dot-W { background: rgba(46,204,113,0.2); color: var(--win); border: 1px solid var(--win); }
  .dot-L { background: rgba(232,69,60,0.2);  color: var(--loss); border: 1px solid var(--loss); }
  .dot-D { background: rgba(245,166,35,0.2); color: var(--draw); border: 1px solid var(--draw); }

  /* ── EMPTY / ERROR ── */
  .placeholder {
    padding: 40px 24px;
    text-align: center;
    color: var(--muted);
    font-size: 0.85rem;
  }
  .placeholder span { display: block; font-size: 2rem; margin-bottom: 8px; }

  .error-msg {
    background: rgba(232,69,60,0.1);
    border: 1px solid rgba(232,69,60,0.3);
    border-radius: 8px;
    padding: 16px 20px;
    color: #ff7b75;
    font-size: 0.85rem;
    margin: 16px;
  }

  /* ── RESPONSIVE ── */
  @media (max-width: 900px) {
    .container { grid-template-columns: 1fr; }
  }
  @media (max-width: 600px) {
    header { padding: 12px 16px; }
    .container { padding: 16px; }
    .logo { font-size: 1.4rem; }
  }
</style>
</head>
<body>

<div id="loading-bar"></div>

<header>
  <div>
    <div class="logo">AFL Premiership Window</div>
    <div class="subtitle">Live Ladder &amp; Team Insights</div>
  </div>
  <div id="season-badge">Loading…</div>
</header>

<div class="container">
  <!-- LEFT: Chart + ladder -->
  <div class="chart-section">
    <div class="section-title">Premiership Window</div>
    <div id="chart-wrap">
      <canvas id="chart-canvas"></canvas>
      <div class="legend">
        <div class="legend-item"><div class="legend-dot" style="background:#f5a623"></div> Top 4</div>
        <div class="legend-item"><div class="legend-dot" style="background:#7ec8e3"></div> Finals (5–8)</div>
        <div class="legend-item"><div class="legend-dot" style="background:#444d6a"></div> Outside Finals</div>
        <div class="legend-item"><div class="legend-dot" style="background:#e8453c; opacity:.8"></div> Selected</div>
      </div>
    </div>

    <div class="section-title" style="margin-top:8px">Current Ladder</div>
    <div class="ladder-card">
      <div class="ladder-header">
        <span>#</span><span>Team</span><span style="text-align:center">W</span><span style="text-align:center">L</span><span style="text-align:center">D</span><span style="text-align:right">Pts</span>
      </div>
      <div id="ladder-body">
        <div class="placeholder"><span>⏳</span>Fetching ladder…</div>
      </div>
    </div>
  </div>

  <!-- RIGHT: Team detail -->
  <div class="ladder-section">
    <div class="section-title">Team Detail</div>
    <div id="detail-panel">
      <!-- filled by JS -->
    </div>
    <div id="detail-placeholder" class="ladder-card">
      <div class="placeholder"><span>👆</span>Click a team on the chart<br>or ladder to see details</div>
    </div>
  </div>
</div>

<script>
// ────────────────────────────────────────────────
// CONFIG
// ────────────────────────────────────────────────
const API = 'https://api.squiggle.com.au/';
const PROXY = '/proxy?url=';   // our Python proxy

// AFL team colours (primary)
const TEAM_COLORS = {
  'Adelaide':         '#002b5c',
  'Brisbane Lions':   '#a30046',
  'Carlton':          '#002f6c',
  'Collingwood':      '#000000',
  'Essendon':         '#cc2031',
  'Fremantle':        '#2c3e6b',
  'Geelong':          '#1c3c6b',
  'Gold Coast':       '#e2242b',
  'Greater Western Sydney': '#f47920',
  'Hawthorn':         '#4d2004',
  'Melbourne':        '#0033a0',
  'North Melbourne':  '#003087',
  'Port Adelaide':    '#008aab',
  'Richmond':         '#ffd200',
  'St Kilda':         '#ed0f05',
  'Sydney':           '#ed171f',
  'West Coast':       '#002b7f',
  'Western Bulldogs': '#0038a8',
};

// ────────────────────────────────────────────────
// STATE
// ────────────────────────────────────────────────
let standings = [];
let gamesMap  = {};   // teamId -> last game
let selectedTeam = null;

// ────────────────────────────────────────────────
// FETCH helpers
// ────────────────────────────────────────────────
async function apiFetch(params) {
  const qs = new URLSearchParams(params).toString();
  const url = encodeURIComponent(API + '?' + qs);
  const res = await fetch(PROXY + url);
  if (!res.ok) throw new Error('HTTP ' + res.status);
  return res.json();
}

// ────────────────────────────────────────────────
// LOADING BAR
// ────────────────────────────────────────────────
let loadPct = 0;
function setLoad(pct) {
  loadPct = pct;
  document.getElementById('loading-bar').style.width = pct + '%';
  if (pct >= 100) setTimeout(() => { document.getElementById('loading-bar').style.opacity = '0'; }, 400);
}

// ────────────────────────────────────────────────
// MAIN LOAD
// ────────────────────────────────────────────────
async function load() {
  setLoad(10);
  try {
    // 1. Get standings
    const sData = await apiFetch({ q: 'standings' });
    standings = sData.standings || [];
    setLoad(40);

    // 2. Get latest completed games for each team
    const gData = await apiFetch({ q: 'games', complete: '100' });
    const allGames = gData.games || [];
    // Index: teamid -> most recent game
    allGames.sort((a,b) => b.date.localeCompare(a.date));
    allGames.forEach(g => {
      if (g.hscore !== null && g.ascore !== null) {
        if (!gamesMap[g.hteamid]) gamesMap[g.hteamid] = { game: g, side: 'home' };
        if (!gamesMap[g.ateamid]) gamesMap[g.ateamid] = { game: g, side: 'away' };
      }
    });
    setLoad(80);

    // Season badge
    if (standings.length) {
      document.getElementById('season-badge').textContent = (standings[0].year || '') + ' Season';
    }

    renderLadder();
    drawChart();
    setLoad(100);
  } catch (e) {
    setLoad(100);
    document.getElementById('ladder-body').innerHTML =
      `<div class="error-msg">⚠️ Could not load AFL data.<br><small>${e.message}</small></div>`;
  }
}

// ────────────────────────────────────────────────
// LADDER RENDER
// ────────────────────────────────────────────────
function renderLadder() {
  const body = document.getElementById('ladder-body');
  body.innerHTML = '';

  standings.forEach((t, i) => {
    const pos = i + 1;

    // Top 8 divider
    if (pos === 9) {
      const div = document.createElement('div');
      div.className = 'top8-divider';
      body.appendChild(div);
    }

    const row = document.createElement('div');
    row.className = 'ladder-row' + (pos <= 8 ? ' top8' : '');
    row.dataset.id = t.id || t.teamid;
    row.innerHTML = `
      <div class="pos-num ${pos<=4?'top4':pos<=8?'top8':''}">${pos}</div>
      <div class="team-name-cell">${t.name}</div>
      <div class="num-cell">${t.wins ?? t.w ?? '–'}</div>
      <div class="num-cell">${t.losses ?? t.l ?? '–'}</div>
      <div class="num-cell">${t.draws ?? t.d ?? '–'}</div>
      <div class="pts-cell">${t.pts ?? '–'}</div>
    `;
    row.addEventListener('click', () => selectTeam(t, pos));
    body.appendChild(row);
  });
}

// ────────────────────────────────────────────────
// CHART DRAW
// ────────────────────────────────────────────────
function drawChart() {
  const canvas  = document.getElementById('chart-canvas');
  const wrap    = document.getElementById('chart-wrap');
  const W       = wrap.clientWidth - 48;
  const n       = standings.length;
  const barH    = 34;
  const gap     = 8;
  const H       = n * (barH + gap) + 60;

  canvas.width  = W;
  canvas.height = H;
  canvas.style.height = H + 'px';

  const ctx = canvas.getContext('2d');
  ctx.clearRect(0, 0, W, H);

  const maxPts  = standings[0]?.pts || 48;
  const padL    = 130;
  const padR    = 50;
  const chartW  = W - padL - padR;

  // Title axis
  ctx.fillStyle  = '#6b7a99';
  ctx.font       = '500 11px DM Sans';
  ctx.textAlign  = 'right';
  ctx.fillText('Points', padL - 8, 14);

  // Top 8 bg band
  const band8H = 8 * (barH + gap) - gap;
  ctx.fillStyle = 'rgba(245,166,35,0.04)';
  ctx.beginPath();
  ctx.roundRect(padL, 30, chartW, band8H, 4);
  ctx.fill();

  // Top 8 label
  ctx.fillStyle = 'rgba(245,166,35,0.35)';
  ctx.font = 'bold 9px DM Sans';
  ctx.textAlign = 'right';
  ctx.fillText('FINALS', W - 4, 30 + band8H / 2 + 4);

  standings.forEach((t, i) => {
    const pos   = i + 1;
    const y     = 30 + i * (barH + gap);
    const pts   = t.pts || 0;
    const bw    = Math.max(4, (pts / maxPts) * chartW);

    // Bar color
    let color;
    if (selectedTeam && (selectedTeam.id === t.id || selectedTeam.name === t.name)) {
      color = '#e8453c';
    } else if (pos <= 4) {
      color = '#f5a623';
    } else if (pos <= 8) {
      color = '#7ec8e3';
    } else {
      color = '#444d6a';
    }

    // Bar shadow / glow for selected
    if (selectedTeam && (selectedTeam.id === t.id || selectedTeam.name === t.name)) {
      ctx.shadowColor = '#e8453c';
      ctx.shadowBlur  = 10;
    } else {
      ctx.shadowBlur = 0;
    }

    // Draw bar
    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.roundRect(padL, y, bw, barH, 4);
    ctx.fill();
    ctx.shadowBlur = 0;

    // Points label on bar end
    ctx.fillStyle = '#fff';
    ctx.font = 'bold 12px DM Sans';
    ctx.textAlign = 'left';
    ctx.fillText(pts, padL + bw + 6, y + barH / 2 + 4);

    // Team name label
    ctx.fillStyle = (selectedTeam && (selectedTeam.id === t.id || selectedTeam.name === t.name))
      ? '#f5a623' : '#d0d8f0';
    ctx.font = (selectedTeam && (selectedTeam.id === t.id || selectedTeam.name === t.name))
      ? 'bold 12px DM Sans' : '500 11px DM Sans';
    ctx.textAlign  = 'right';
    const shortName = t.name.replace('Greater Western Sydney','GWS').replace('Western Bulldogs','W. Bulldogs').replace('Brisbane Lions','Brisbane').replace('North Melbourne','N. Melbourne');
    ctx.fillText(shortName, padL - 8, y + barH / 2 + 4);

    // Position pill
    ctx.fillStyle = pos <= 4 ? '#f5a623' : pos <= 8 ? '#7ec8e3' : '#555e80';
    ctx.beginPath();
    ctx.roundRect(padL - 8 - 22, y + barH/2 - 8, 20, 16, 3);
    ctx.fill();
    ctx.fillStyle = pos <= 8 ? '#000' : '#aaa';
    ctx.font = 'bold 9px DM Sans';
    ctx.textAlign = 'center';
    ctx.fillText(pos, padL - 8 - 12, y + barH/2 + 4);
  });

  // Click handler
  canvas.onclick = (e) => {
    const rect = canvas.getBoundingClientRect();
    const scaleX = canvas.width / rect.width;
    const scaleY = canvas.height / rect.height;
    const cx = (e.clientX - rect.left) * scaleX;
    const cy = (e.clientY - rect.top)  * scaleY;

    standings.forEach((t, i) => {
      const y = 30 + i * (barH + gap);
      if (cy >= y && cy <= y + barH) {
        selectTeam(t, i + 1);
      }
    });
  };
}

// ────────────────────────────────────────────────
// SELECT TEAM
// ────────────────────────────────────────────────
function selectTeam(t, pos) {
  selectedTeam = t;

  // Highlight ladder row
  document.querySelectorAll('.ladder-row').forEach(r => r.classList.remove('selected'));
  document.querySelectorAll('.ladder-row').forEach(r => {
    if (r.dataset.id == (t.id || t.teamid)) r.classList.add('selected');
  });

  // Redraw chart
  drawChart();

  // Show detail panel
  showDetail(t, pos);
}

// ────────────────────────────────────────────────
// DETAIL PANEL
// ────────────────────────────────────────────────
function showDetail(t, pos) {
  const panel = document.getElementById('detail-panel');
  const ph    = document.getElementById('detail-placeholder');

  ph.style.display = 'none';
  panel.style.display = 'block';
  panel.innerHTML = '';  // clear + re-animate
  void panel.offsetWidth;

  const wins   = t.wins   ?? t.w ?? 0;
  const losses = t.losses ?? t.l ?? 0;
  const draws  = t.draws  ?? t.d ?? 0;
  const pts    = t.pts    ?? 0;
  const pct    = t.percentage ? t.percentage.toFixed(1) + '%' : '–';

  // Window score: 0-100, higher = more "open" window
  // Formula: based on position (inverse), pts % of leader, recent form
  const leaderPts = standings[0]?.pts || 1;
  const posScore  = Math.max(0, 100 - (pos - 1) * (100/18));
  const ptsScore  = (pts / leaderPts) * 100;
  const windowPct = Math.round((posScore * 0.6 + ptsScore * 0.4));

  let windowDesc;
  if (pos === 1)      windowDesc = 'Leading the competition — premiership window is wide open.';
  else if (pos <= 4)  windowDesc = 'Top 4 position — double-chance secured. Finals prospects are excellent.';
  else if (pos <= 8)  windowDesc = 'Inside the 8 — finals are in reach but competition is fierce.';
  else if (pos <= 12) windowDesc = 'Hunting finals — needs a strong run to crack the 8.';
  else                windowDesc = 'Rebuilding phase — focus is on 2025 draft and development.';

  // Last game
  const entry = gamesMap[t.id] || gamesMap[t.teamid];
  let resultHTML = '<div class="placeholder" style="padding:20px 0"><span>📭</span>No recent game data</div>';

  if (entry) {
    const g    = entry.game;
    const side = entry.side;
    const teamScore = side === 'home' ? g.hscore : g.ascore;
    const oppScore  = side === 'home' ? g.ascore  : g.hscore;
    const oppName   = side === 'home' ? g.ateam   : g.hteam;
    const won = teamScore > oppScore;
    const drew= teamScore === oppScore;
    const badge = drew ? '<span class="draw-badge">Draw</span>'
                : won  ? '<span class="win-badge">Win</span>'
                       : '<span class="loss-badge">Loss</span>';
    const dateStr = g.date ? new Date(g.date).toLocaleDateString('en-AU',{weekday:'short',day:'numeric',month:'short'}) : '';
    const venue   = g.venue || '';

    resultHTML = `
      <div class="result-card">
        <div class="result-teams">
          <div>
            <div class="result-team">${t.name}</div>
            <div class="result-score" style="color:${won?'var(--win)':drew?'var(--draw)':'var(--loss)'}">${teamScore ?? '–'}</div>
          </div>
          <span class="vs-badge">VS</span>
          <div style="text-align:right">
            <div class="result-team">${oppName}</div>
            <div class="result-score" style="color:var(--muted)">${oppScore ?? '–'}</div>
          </div>
        </div>
        <div class="result-meta">
          <span>${badge}</span>
          <span>${dateStr}${venue ? ' · ' + venue : ''}</span>
        </div>
      </div>`;
  }

  // Form string from standings if available
  const formStr = t.form || '';
  let dotsHTML  = '';
  if (formStr) {
    [...formStr].forEach(ch => {
      const cls = ch === 'W' ? 'dot-W' : ch === 'L' ? 'dot-L' : 'dot-D';
      dotsHTML += `<div class="dot ${cls}">${ch}</div>`;
    });
  }

  panel.innerHTML = `
    <div class="detail-hero">
      <div class="detail-team-name">${t.name}</div>
      <div class="detail-pos">Position ${pos} · ${pts} pts · ${pct}</div>
    </div>
    <div class="detail-stats">
      <div class="stat-box">
        <div class="stat-val" style="color:var(--win)">${wins}</div>
        <div class="stat-lbl">Wins</div>
      </div>
      <div class="stat-box">
        <div class="stat-val" style="color:var(--loss)">${losses}</div>
        <div class="stat-lbl">Losses</div>
      </div>
      <div class="stat-box">
        <div class="stat-val" style="color:var(--draw)">${draws}</div>
        <div class="stat-lbl">Draws</div>
      </div>
    </div>
    <div class="last-result">
      <h3>Last Result</h3>
      ${resultHTML}
    </div>
    ${dotsHTML ? `<div class="form-dots"><h3>Recent Form (oldest → latest)</h3><div class="dots-row">${dotsHTML}</div></div>` : ''}
    <div class="window-meter">
      <h3>Premiership Window</h3>
      <div class="meter-bar-wrap">
        <div class="meter-bar" style="width:0%" id="meter-fill"></div>
      </div>
      <div class="meter-labels"><span>Closed</span><span>Open</span></div>
      <div class="window-desc">${windowDesc}</div>
    </div>
  `;

  // Animate meter
  requestAnimationFrame(() => {
    requestAnimationFrame(() => {
      const fill = document.getElementById('meter-fill');
      if (fill) fill.style.width = windowPct + '%';
    });
  });
}

// ────────────────────────────────────────────────
// RESIZE
// ────────────────────────────────────────────────
let resizeTimer;
window.addEventListener('resize', () => {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(drawChart, 150);
});

// ────────────────────────────────────────────────
// GO
// ────────────────────────────────────────────────
load();
</script>
</body>
</html>
"""

# ─── PROXY HANDLER ────────────────────────────────────────────────────────────

class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # suppress console noise

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)

        if parsed.path == '/proxy':
            params = urllib.parse.parse_qs(parsed.query)
            target = params.get('url', [None])[0]
            if not target:
                self._send(400, b'Missing url param', 'text/plain')
                return
            try:
                req = urllib.request.Request(
                    target,
                    headers={'User-Agent': 'AFLPremiershipWindow/1.0 (github.com/squiggle)'}
                )
                with urllib.request.urlopen(req, timeout=10) as r:
                    data = r.read()
                self._send(200, data, 'application/json')
            except Exception as e:
                self._send(502, str(e).encode(), 'text/plain')

        elif parsed.path in ('/', '/index.html'):
            self._send(200, HTML.encode(), 'text/html; charset=utf-8')

        else:
            self._send(404, b'Not found', 'text/plain')

    def _send(self, code, body, ctype):
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', len(body))
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(body)


# ─── MAIN ─────────────────────────────────────────────────────────────────────

PORT = 8080

if __name__ == '__main__':
    server = http.server.HTTPServer(('0.0.0.0', PORT), Handler)
    print(f"""
╔══════════════════════════════════════════════╗
║   AFL Premiership Window Dashboard           ║
╠══════════════════════════════════════════════╣
║  Server: http://localhost:{PORT}               ║
║  Data:   api.squiggle.com.au (live)          ║
║  Stop:   Ctrl+C                              ║
╚══════════════════════════════════════════════╝
""")

    # Auto-open browser
    def open_browser():
        import time; time.sleep(0.8)
        webbrowser.open(f'http://localhost:{PORT}')

    threading.Thread(target=open_browser, daemon=True).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\nShutdown.')
        server.shutdown()
        sys.exit(0)
