# Margin — AFL predictions landing page

A self-contained, responsive marketing site for the **AFL prediction model** in
this repo. Same polished, dobre-inspired design language (light/minimal, big
typography, cobalt accent, scroll animations) — every section is now about the
predictor: win probabilities, calibrated player props, Same Game Multis and Elo.
**No build step, no framework.**

It pairs with the Streamlit dashboard (`app/`): the landing page sells the model,
the "Launch dashboard" buttons point at the live app.

## Run it

```bash
open index.html                                   # just open it, or…
python3 -m http.server 8000 --directory .         # then http://localhost:8000
```

The **Launch dashboard** links point at `http://localhost:8504` — start the
Streamlit app first (`streamlit run app/streamlit_app.py`) for those to work, or
change the URL to your deployed dashboard.

## Sections

Header → hero (*"Predict every AFL game. Down to the disposal."*) → marquee →
honest-probabilities statement → **Win probabilities** (sample fixture cards with
probability bars + PICK badges) → **What it does** (predictions, props, SGMs, Elo,
value, calibration) → **stats** (67% tip accuracy, 44,850 player-games, …) →
**Under the hood** (the model) → **Pipeline** (data → rate → project → calibrate)
→ **Get access** (email capture + dashboard link) → footer with responsible-
gambling notice.

## Make it yours

- **Numbers / copy**: the stats and sample fixtures are the model's real figures
  (2026 R16). Update them in `index.html`, or wire the page to the live app.
- **Colour**: change `--accent` at the top of `styles.css` to re-theme everything.
- **Fixtures**: each `.fixture` card is plain HTML — swap teams, %s (also set the
  `.pbar__home` width to match), venue and leader. Or generate them from the model.
- **Dashboard URL**: replace `http://localhost:8504` when you deploy the app.

## The hero animation

The front page opens with a Dobre-style centred graphic: floating pills (brand +
menu, corner labels) over a full-screen **animated AFL field**. `field.js` draws
an oval (boundary, centre square/circle, 50m arcs, goal-post ticks) on a canvas,
with 18 player circles (two teams) that wander and loosely contest, and an orange
ball that gets **passed between players** with an arc and a fading trail; the
holder gets a cobalt ring. The centred caption rotates through phrases
("Calibrated Predictions", "Win Probabilities", …).

> Note: the animation uses `requestAnimationFrame`, which browsers pause when the
> tab isn't visible — so it animates in a normal browser tab but looks static in
> a hidden/headless one. It also honours `prefers-reduced-motion` (renders a
> single still frame).

Files: `index.html` (content), `styles.css` (theme + layout + fixture/prob-bar +
hero components), `script.js` (mobile menu, scroll-reveal, stat counters, signup
demo, caption rotator), `field.js` (the canvas AFL-field animation). Reduced-
motion and no-JS fallbacks included.
