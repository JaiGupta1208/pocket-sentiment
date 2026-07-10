# Pocket — Voice of Customer dashboard (Task 3)

A social-listening system for **Pocket** (Open Vision Engineering's screenless AI voice
recorder). It pulls what people say about Pocket across the public web, classifies each
mention for sentiment + theme, and presents it as one live dashboard.

**Live dashboard:** _<add Streamlit Cloud URL after deploy>_

---

## The 4 layers

```
 Collectors (one per source)              Store            Logic              Dashboard
 ─────────────────────────────           ───────         ───────            ───────────
 App Store  reviews  (page JSON)  ┐
 Google Play reviews (scraper)    │
 Reddit posts+comments (browser)  ├──►  SQLite (dedup) ──► Claude ──►  Streamlit (app.py)
 YouTube comments  (Data API v3)  │      mentions tbl      sentiment      Overview / Themes /
 Trustpilot* X* Meta* TikTok*     ┘      common schema     + themes       Sources / Feed / Ops
                                                           + confidence
 * labeled MOCK in this build (see "Sources" below)
```

1. **Collect** — `collectors/*.py`, one small script per source, each normalizing to a
   common schema (`source, native_id, kind, author, text, rating, created_at, url`).
2. **Store** — `store.py`, a single SQLite file (`data/mentions.db`). Dedup by
   `sha1(source + native_id)`, so re-running collectors only adds new rows.
3. **Classify** — `classify.py`. Claude batch-scores each row: `sentiment`
   (positive/negative/neutral/mixed), 1–3 `themes` from a fixed taxonomy, a `relevant`
   flag, and a `confidence`. A transparent rule-based fallback runs when no API key is set.
4. **Dashboard** — `app.py`, Streamlit. Five views (below).

## Sources

| Source | Status | How | Rows |
|---|---|---|---|
| App Store | **real** | review objects Apple server-renders into the app page (`id 6746845735`) | ~40 |
| Google Play | **real** | `google-play-scraper` (`com.heypocket.app`) | ~165 |
| Reddit | **real** | public `.json` endpoints, run from a logged-in browser tab (datacenter IPs are 403'd) | ~265 |
| YouTube | **real** | Data API v3 — search Pocket videos, pull their comments | ~310 |
| Trustpilot | *mock* | real reviews exist (`heypocket.com`, ~925) but sit behind AWS WAF; prod path = Trustpilot Business API or authenticated scrape |
| X / Twitter | *mock* | search API is $200+/mo, no free tier |
| Facebook / Instagram | *mock* | Meta Graph API only serves Pages you own |
| TikTok | *mock* | no official public comment API |

Mock rows are written with `is_mock=1`, badged in the UI, and excluded from headline
numbers by default. Their text mirrors themes that genuinely surfaced in public summaries,
so the demo is realistic without pretending to be real data.

> **Why the Reddit browser step?** Reddit blocks server/datacenter IPs on the JSON
> endpoints. The fetch logic in `collectors/reddit.py` is identical; it just has to run
> from a residential IP. In production this is a cheap residential proxy or a Reddit OAuth
> script-app credential. The browser JS used to produce `pocket_reddit.json` is at the
> bottom of this file.

## The logic (sentiment + themes) & QA

- **Model:** Claude (`claude-sonnet-5`), batched ~20 items/call, structured JSON out.
- **Taxonomy:** 16 fixed themes (transcription accuracy, summary quality, battery,
  recording quality, hardware build, magnet, reliability, app, search, shipping, support,
  price/value, privacy, setup, competitor, general) so aggregates stay clean.
- **QA:** every row carries a `confidence`; the Feed view can be filtered to low-confidence
  rows for spot-checking, and rated sources (App Store/Play/Trustpilot) give a free
  ground-truth signal — star rating vs. predicted sentiment should correlate. Hold out a
  ~50-row sample, hand-label, measure agreement; re-tune the prompt if <~85%.

## The ops

- **Cadence:** reviews + social pulled daily (hourly during a launch). Classifier only
  touches new rows.
- **Owner:** ~15 min/day skim the negative feed; weekly the founder reads the Themes tab
  and picks one fix.
- **Alerts:** Slack ping if negative share >30% over rolling 24h; any 1★ mentioning
  `shipping`/`damaged`; volume spike >3× the trailing-7-day average.
- **Cost:** classifier is the only variable cost — **< $1/mo today** (~800 new/mo),
  **~$5–8/mo at 10×**. Collection APIs are free tiers / free quota; hosting is Streamlit
  Community Cloud (free).

## Dashboard views

- **Overview** — totals, positive/negative %, avg star rating, sentiment mix, weekly
  volume-and-sentiment trend.
- **Themes** — sentiment-split theme bars + a "most negative themes, fix first" table.
- **Sources** — volume by source and a per-source scorecard (mentions, %positive, avg
  rating, real/mock).
- **Feed** — filterable raw stream (sentiment / theme / text search) with links back to
  the original post.
- **Pipeline & Ops** — the diagram, cadence, owner, alerts, cost table.

## Run it

```bash
pip install -r requirements.txt

# 1. collect (App Store / Play / YouTube / mocks run headless; Reddit uses the browser export)
python run_all.py

# 2. classify — set your key first for the Claude pass, else it falls back to rules
#    (put ANTHROPIC_API_KEY in .env)
python classify.py

# 3. dashboard
streamlit run app.py
```

Secrets live in `.env` locally (git-ignored) and in Streamlit Cloud's Secrets manager in
prod. `data/mentions.db` is committed as the snapshot the hosted dashboard reads.

<details><summary>Reddit browser-export JS (paste into a logged-in reddit.com tab console)</summary>

Fetches search results + top-level comments across a few queries and downloads
`pocket_reddit.json`, which `collectors/reddit.py` then loads. Kept because Reddit 403s
datacenter IPs. (See git history / the collector docstring for the exact snippet.)

</details>
