"""Page 3 — SGM Creator: safest Same Game Multi + a manual builder."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd
import streamlit as st

import _shared as sh
from afl.odds import sgm

st.set_page_config(page_title="AFL Predictor — SGM", page_icon="🎲", layout="wide")
st.title("🎲 Same Game Multi Creator")
st.caption("Build a SportsBet SGM from every integer milestone line. 'Safest' = "
           "most likely (per the calibrated model) to fully land at the target.")

events = sh.upcoming_events()
if events.empty:
    st.warning("No upcoming AFL games from the odds feed right now.")
    st.stop()

labels = {f"{r['home_team']} v {r['away_team']}  ·  "
          f"{pd.to_datetime(r['commence_time']).strftime('%a %d %b')}": r
          for _, r in events.iterrows()}
choice = st.selectbox("Select a game", list(labels))
ev = labels[choice]
home, away = ev["home_team"], ev["away_team"]
venue, when = sh.fixture_venues(2026).get((home, away), ("", None))

legs = sh.priced_legs(ev["id"], home, away, venue, when)
if legs.empty:
    st.warning("No player markets available for this game yet.")
    st.stop()

auto_tab, manual_tab = st.tabs(["⚡ Safest auto", "🛠 Build your own"])

# ---------------------------------------------------------------------------
with auto_tab:
    c1, c2, c3 = st.columns(3)
    targets = c1.multiselect("Target multipliers", [2, 3, 5, 10, 20, 50],
                             default=[2, 3, 5, 10])
    max_per_stat = c2.selectbox(
        "Max legs per stat (diversify)", [None, 1, 2, 3],
        format_func=lambda x: "no limit" if x is None else str(x))
    max_legs = c3.slider("Max legs", 2, 10, 7)

    for t in sorted(targets):
        res = sgm.safest_multi(legs, float(t), max_legs=max_legs,
                               max_per_stat=max_per_stat)
        with st.container(border=True):
            if res is None:
                st.markdown(f"**~{t}×** — no safe combination from available lines.")
                continue
            head, metric = st.columns([3, 2])
            with head:
                st.markdown(f"### Safest ~{t}×  ·  {res['n_legs']} legs")
                tbl = pd.DataFrame([{
                    "leg": f"{l['player']}  {l['milestone']}",
                    "odds": round(l["odds"], 2),
                    "model P": f"{l['prob']*100:.0f}%",
                } for l in res["legs"]])
                st.table(tbl)
            with metric:
                st.metric("Combined odds", f"{res['combined_odds']:.2f}×")
                st.metric("Model P(all land)", f"{res['joint_prob']*100:.1f}%",
                          help="Independence estimate — optimistic; see caveats.")
                st.metric("Book-implied (breakeven)",
                          f"{res['implied_prob']*100:.1f}%")
            if len({l["stat"] for l in res["legs"]}) == 1:
                st.warning(f"All legs are {res['legs'][0]['stat']} — they move "
                           "together (a slow game sinks them all), so the true "
                           "hit-rate is lower than shown. Try 'Max legs per stat'.")

# ---------------------------------------------------------------------------
with manual_tab:
    st.caption("Pick legs and watch the combined odds and joint probability update.")
    pool = legs.copy()
    pool["label"] = (pool["player"] + "  " + pool["milestone"]
                     + "   @" + pool["odds"].round(2).astype(str)
                     + "  (" + (pool["prob"] * 100).round(0).astype(int).astype(str)
                     + "%)")
    pool = pool.sort_values(["player", "stat", "line"])
    picked = st.multiselect("Add legs", pool["label"].tolist())
    chosen = pool[pool["label"].isin(picked)]

    if chosen.empty:
        st.info("Add at least two legs to form a multi.")
    else:
        combined = float(np.prod(chosen["odds"]))
        joint = float(np.prod(chosen["prob"]))
        m1, m2, m3 = st.columns(3)
        m1.metric("Legs", len(chosen))
        m2.metric("Combined odds", f"{combined:.2f}×")
        m3.metric("Model P(all land)", f"{joint*100:.1f}%")
        st.table(chosen[["player", "milestone", "stat", "odds", "prob"]]
                 .assign(prob=lambda d: (d["prob"] * 100).round(0).astype(int)
                         .astype(str) + "%",
                         odds=lambda d: d["odds"].round(2))
                 .rename(columns={"prob": "model P"}))
        dupes = chosen["player_scraped"].duplicated().any()
        if dupes:
            st.error("You've picked two legs for the same player — SportsBet "
                     "usually blocks correlated same-player legs in an SGM.")
        if chosen["stat"].nunique() == 1 and len(chosen) > 1:
            st.warning("All legs share one stat — correlated; the real hit-rate "
                       "is lower than the independent estimate above.")

st.divider()
st.caption("Combined odds = product of legs; SportsBet's real SGM price applies "
           "correlation adjustments and is usually shorter. The model's edge is "
           "largest on juiced favourite milestones, where it's most likely "
           "overconfident — treat the joint probability as an optimistic ceiling. "
           "Gamble responsibly.")
