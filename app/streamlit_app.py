"""AFL Predictor — Game Predictions (home page)."""
from __future__ import annotations

import _shared as sh
import pandas as pd
import streamlit as st

st.set_page_config(page_title="AFL Predictor — Games", page_icon="🏉", layout="wide")

st.title("🏉 AFL Predictor")
st.caption("Win probabilities and expected match leaders, from Elo + form + "
           "head-to-head + weather, with calibrated player projections.")

_adj = sh.adjustments.current()
if _adj is not None:
    st.success(
        f"🧠 Online-learned adjustments active (walk-forward from R{_adj.cutoff_round} "
        f"{_adj.year}): home-ground edge **{_adj.hga:.0f}** Elo pts, win-prob "
        f"calibration **a={_adj.cal_a:.2f}/b={_adj.cal_b:.2f}**, "
        f"player bias **{ {k: round(v,1) for k,v in _adj.player_bias.items()} }**.",
        icon="🧠")

col_y, col_r, _ = st.columns([1, 1, 4])
year = col_y.number_input("Season", min_value=2015, max_value=2030, value=2026, step=1)
nr = sh.next_round(int(year))
rnd = col_r.number_input("Round", min_value=1, max_value=30,
                         value=int(nr) if nr else 1, step=1)

preds = sh.round_predictions(int(year), int(rnd))
if preds.empty:
    st.warning("No fixtures found for that round.")
    st.stop()

if sh.win_model() is None:
    st.info("No trained win model found — showing Elo-based probabilities. "
            "Run `python scripts/train.py` to train the full model.")

st.subheader(f"Round {int(rnd)} — {len(preds)} games")

for _, g in preds.iterrows():
    with st.container(border=True):
        head, prob = st.columns([2, 3])
        with head:
            st.markdown(f"### {g['home']}  v  {g['away']}")
            when = pd.to_datetime(g["date"]).strftime("%a %d %b, %I:%M %p")
            st.caption(f"📍 {g['venue'] or 'TBC'}  ·  {when}")
            st.markdown(f"**Pick: :green[{g['pick']}]**")
            wx = []
            if g["rain_mm"] and g["rain_mm"] >= 1:
                wx.append(f"🌧 {g['rain_mm']:.0f}mm")
            if g["wind_kmh"] and g["wind_kmh"] >= 30:
                wx.append(f"💨 {g['wind_kmh']:.0f}km/h")
            st.caption(("  ·  ".join(wx) if wx else "☀ fine")
                       + f"   ·   H2H last 10: {g['h2h']}")
        with prob:
            ph = float(g["p_home"])
            st.markdown(f"**{g['home']}**  ·  {ph*100:.0f}%")
            st.progress(ph)
            st.markdown(f"**{g['away']}**  ·  {(1-ph)*100:.0f}%")
            st.progress(1 - ph)

        kp = sh.game_key_players(g["home"], g["away"], g["venue"],
                                 pd.to_datetime(g["date"]).isoformat())
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**🥇 Expected leading disposals**")
            for name, team, val in kp["top_disposals"]:
                st.markdown(f"- {name} *({team})* — **{val:.0f}**")
        with c2:
            st.markdown("**⚽ Expected leading goals**")
            for name, team, val in kp["top_goals"]:
                st.markdown(f"- {name} *({team})* — **{val:.1f}**")

st.divider()
st.caption("Projections are estimates from public data. No model beats the "
           "closing line consistently — bet responsibly.")
