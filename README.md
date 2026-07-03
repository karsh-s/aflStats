# AFL Prediction Model

Predicts AFL match winners and player-prop outcomes from **Elo, recent form,
head-to-head history, venue, and weather**, then compares the model's
probabilities against bookmaker odds (via The Odds API, which includes
Sportsbet's lines under the `au` region) to surface **value bets**.

Built as an importable library (`afl/`) with thin CLI scripts (`scripts/`), so
the same logic can back a Streamlit/Flask web app later.

---

## What it does

| Capability | How |
|---|---|
| **Match-winner probability** | Calibrated gradient-boosted model over Elo + form + H2H + weather features |
| **Team Elo** | HGA, margin-of-victory scaling, between-season regression |
| **Player Elo** | Per-stat running skill rating (disposals, goals, marks, tackles) with opponent-defence adjustment |
| **Player props** | Projects a player's stat + wraps it in a Poisson/Negative-Binomial distribution → **P(over/under any line)** |
| **Same Game Multis** | Safest SportsBet SGM for a 2x/3x/5x/10x target, built from every integer "X+" milestone line |
| **Weather** | Open-Meteo historical archive (training) + forecast (upcoming); roofed venues treated as neutral |
| **Head-to-head** | Direct H2H record and recent-meeting win rate / margin |
| **Value betting** | Implied prob, vig removal (de-vig), edge, EV per unit, fractional-Kelly stake |

## Data sources (all free)

- **Squiggle API** — fixtures, results, venues, ladder. No key.
- **AFL Tables** — per-player box scores (scraped, cached). No key.
- **Open-Meteo** — historical + forecast weather. No key.
- **The Odds API** — bookmaker H2H / totals / player-prop odds. **Free key required**
  (~500 requests/month): https://the-odds-api.com/

> **On Sportsbet:** Sportsbet has no public API and scraping it violates their
> ToS. The Odds API is a licensed aggregator that *includes* Sportsbet (and TAB,
> Pointsbet, Neds…) under the `au` region, so you still get their prices where
> published — legally and reliably.

---

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env       # then add your ODDS_API_KEY
```

## Usage

```bash
# 1. Download game data (Squiggle). Add --players to also scrape box scores.
python scripts/fetch_data.py --start 2015 --end 2025
python scripts/fetch_data.py --start 2022 --end 2025 --players

# 2. Build features, backtest, and train the winner model.
python scripts/train.py --start 2015 --end 2025
#    (use --no-weather to skip the weather API and train faster)

# 3. Predict a round's win probabilities.
python scripts/predict.py --year 2025 --round 15

# 4. Find value vs bookmaker head-to-head odds (needs ODDS_API_KEY).
python scripts/value_bets.py --year 2025 --min-edge 0.03

# 5a. Project a single player prop line by hand.
python scripts/player_props.py --player "Bontempelli, Marcus" \
    --stat disposals --opponent "Geelong" --home --line 27.5

# 5b. Scan live player-prop markets for value (needs ODDS_API_KEY + box scores).
python scripts/player_props.py --odds --min-edge 0.04 --min-games 8

# 6. (Re)calibrate the prop projections after new data lands.
python scripts/calibrate_props.py --all --reliability

# 7. Build the safest SportsBet Same Game Multi for 2x/3x/5x/10x.
python scripts/sgm.py --team Brisbane
python scripts/sgm.py --targets 2 3 5 10 --max-per-stat 2

# 8. Walk-forward online learning: freeze at Round 5 2026, then predict each
#    later game + every player stat, observe the result, adjust, to present day.
python scripts/walkforward.py
```

## Web app

A 3-page Streamlit app sits on top of the same library:

```bash
streamlit run app/streamlit_app.py
```

- **Game Predictions** — every game in the next round: win probabilities, venue,
  weather, head-to-head, and the expected leading disposal-getters and goal-kickers.
- **Game Props** — pick a game and see every player's full integer milestone
  ladder (9+, 10+, 11+ …) for disposals/goals/tackles as a heat-mapped grid of
  model probabilities, toggleable to SportsBet odds.
- **SGM Creator** — the safest Same Game Multi for each target multiplier, plus a
  manual builder that live-updates combined odds and joint probability as you add
  legs.

Player names follow AFL Tables' `"Surname, First"` format.

---

## How the model works

**Match winner.** Each completed game is walked through chronologically to derive
*leak-free* pre-game features:

- `elo_diff`, `elo_exp_home` — Elo gap (incl. home-ground advantage) and the
  implied win prob.
- `form_*_diff` — rolling 5-game win%, margin, and scoring differentials.
- `rest_days_diff`, `season_win_pct_diff` — schedule and season-to-date form.
- `h2h_home_win_pct`, `h2h_home_avg_margin` — recent direct meetings.
- `temp_max`, `rain_mm`, `wind_kmh` — match-day weather (neutral if roofed).

A `GradientBoostingClassifier` is calibrated (isotonic) so probabilities are
trustworthy enough to bet against. `time_series_backtest` retrains per season and
reports the model **against the raw Elo baseline** — Elo alone is strong in AFL,
so you can see exactly how much the extra features add (accuracy, log-loss,
Brier).

**Player props.** A projection starts from a recency-weighted average of the
player's last games (for disposals/marks this uses **exponential decay** so the
base reacts quickly when a player steps into a bigger role, rather than lagging
behind a flat trailing average; goals/tackles keep a flatter average). It can be
blended with an opponent-aware Elo expectation, then layers on three
**situational splits**, each a sample-size-shrunk additive nudge:

  * **opponent** — their last 5 games vs this specific club,
  * **venue** — their last 5 games at this ground,
  * **weather** — if the forecast is wet (≥1 mm) or windy (≥30 km/h), how they
    perform in those conditions historically.

Each split is **form-adjusted**: instead of comparing a player's games vs an
opponent to their career mean (which conflates "this team suppresses me" with "I
was in worse form that year"), each such game is compared to the player's *local
form* — the 3 games either side that aren't themselves in the split. The
residual is how much the matchup/venue/weather moved them *relative to who they
were at the time*; the effect is the recency-weighted mean residual, shrunk by
`n/(n+shrink)`. The single-line view prints the breakdown
(`base | vs opp | at venue | weather`), and `--explain` shows the per-meeting
residual table. The resulting mean (and the player's own variance) parameterises
a distribution — **Poisson** for goals, **Negative Binomial** for over-dispersed
counts like disposals — and `P(over line)` is read off the survival function.

> Calibrated reality check: AFL matchup/venue/weather effects are real but
> *small and noisy* — recent form already captures most of them. Full-weight
> splits hurt accuracy, so the defaults use small per-stat weights (validated to
> be roughly neutral, and slightly calibration-improving for disposals). Re-run
> `scripts/calibrate_props.py --all` to see the splits-on vs splits-off numbers.

**Value.** For any selection, `P_model` is compared to the de-vigged implied
probability from the book. Positive edge → `EV/unit > 0` → a fractional-Kelly
stake is suggested.

**Same Game Multis.** `scripts/sgm.py` pulls every "X+" milestone SportsBet
posts (e.g. `player_disposals_over` gives 16+, 17+, 18+ … not just the round
numbers), prices each leg with the calibrated model, and finds the **safest**
combination clearing a target multiplier. For target `M` it solves
`maximise Π p_i  s.t.  Π o_i ≥ M`, one leg per player, via a small grouped-
knapsack DP over log-odds — "safest" = the multi most likely to *fully* land.
Two honest caveats it prints: combined odds are the product of legs (SportsBet's
real SGM price is shorter), and stacking same-stat legs (all disposals) is
correlated — a slow game sinks them together — so `--max-per-stat` lets you
diversify. The big model-vs-implied gaps come from heavily-juiced favourite
milestones where the model is most likely overconfident; treat the joint
probability as an optimistic ceiling.

**Prop calibration.** `scripts/calibrate_props.py` runs a leak-free walk-forward
backtest (Elo fit only on pre-cutoff games; each projection uses a player's prior
games only) and reports **bias**, **MAE**, and **ECE** (expected calibration
error — does "70%" actually hit ~70%?). It drove the per-stat defaults in
`player_props.py`. Over full-season windows the projections are near-unbiased and
well-calibrated (ECE ≈ 0.015). Two findings worth knowing:

  * Book disposal lines and our projections agree to within ~0.15 on average, so
    there is **no systematic edge** — as expected against a sharp market. Large
    "edges" almost always mean small samples or stale player info, which is why
    the scan defaults to `--min-games 8`.
  * We deliberately apply **no bias correction**: the larger bias on a tiny
    single-season window did not persist across seasons, so correcting it would
    overfit.

---

## Project layout

```
afl/
  config.py              paths, keys, Elo constants
  http.py                cached, rate-limited HTTP
  data/
    squiggle.py          fixtures / results / ladder
    afltables.py         player box-score scraper
    weather.py           Open-Meteo historical + forecast
    stadiums.py          venue coords, roof, home-ground map
  features/
    elo.py               team Elo
    form.py              rolling form, rest, season win%
    h2h.py               head-to-head
    build.py             assemble the modelling matrix
  model/
    win_model.py         match-winner classifier + backtest
    player_elo.py        per-stat player ratings
    player_props.py      prop projection + line probabilities
    _dist.py             Poisson / Negative-Binomial helpers
  odds/
    theoddsapi.py        The Odds API client
    value.py             implied prob, de-vig, edge, Kelly
  pipeline.py            orchestration shared by scripts (and future web app)
scripts/
  fetch_data.py  train.py  predict.py  value_bets.py  player_props.py
```

## Roadmap to a web app

The CLI is intentionally thin — everything lives in `afl/pipeline.py` and the
library modules. A Streamlit front end would just call `pipeline.load_features`,
`pipeline.load_model`, `build.feature_row_for_fixture`, and the `odds`/`value`
helpers, rendering the same tables interactively.

## Caveats

- Predictions are estimates from public data — **no model beats the closing line
  consistently.** Use the value numbers as a screen, not a guarantee.
- The AFL Tables scraper depends on their HTML; if a page layout changes a game
  is skipped with a warning rather than crashing the run.
- The Odds API free tier is quota-limited; responses are cached 30 min.
- Gambling involves risk. Bet within your means.
```
