"""Pocket — Voice of Customer dashboard (Task 3)."""
import json
import os
import pandas as pd
import plotly.express as px
import streamlit as st

import store

LOGO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "pocket_logo.png")

# The time view starts here: ~all chatter is the launch ramp onward, and a few stray
# older mentions would otherwise stretch every date range across empty years.
TREND_START = pd.Timestamp("2025-12-01", tz="UTC")

st.set_page_config(page_title="Pocket — Voice of Customer", page_icon=LOGO, layout="wide")

SENTIMENT_COLORS = {"positive": "#16a34a", "neutral": "#9ca3af", "negative": "#dc2626", "mixed": "#f59e0b"}
SOURCE_LABELS = {
    "appstore": "App Store", "play": "Google Play", "reddit": "Reddit", "youtube": "YouTube",
    "trustpilot": "Trustpilot", "x": "X / Twitter", "facebook": "Facebook",
    "instagram": "Instagram", "tiktok": "TikTok",
}

# Fixed classification taxonomy (mirrors classify.py). Used for theme-drift QA.
THEME_TAXONOMY = [
    "transcription_accuracy", "summary_quality", "battery_life", "audio_recording_quality",
    "hardware_build", "magnet_attachment", "device_reliability", "app_experience",
    "search_organization", "shipping_delivery", "customer_support", "price_value",
    "privacy", "ease_of_setup", "comparison_competitor", "general_praise",
]

# How each source is collected today, and the production path if mocked.
SOURCE_STATUS = {
    "appstore":  ("Real", "Public App Store review feed parsed from the app page."),
    "play":      ("Real", "google-play-scraper over the public Play listing."),
    "reddit":    ("Real", "Public Reddit JSON via a browser-session export (residential IP)."),
    "youtube":   ("Real", "Official YouTube Data API v3 (search + commentThreads)."),
    "trustpilot":("Mock", "Prod: Trustpilot Business API or approved authenticated collection."),
    "x":         ("Mock", "Prod: paid X API tier or an approved social-listening provider."),
    "facebook":  ("Mock", "Prod: Meta Graph API for owned pages, or an approved provider."),
    "instagram": ("Mock", "Prod: Meta Graph API for owned accounts, or an approved provider."),
    "tiktok":    ("Mock", "Prod: approved TikTok API or a social-listening provider."),
}


def _parse_themes(s):
    """Tolerant: never let a bad themes value crash the dashboard."""
    if not s:
        return []
    try:
        v = json.loads(s)
        return v if isinstance(v, list) else []
    except (ValueError, TypeError):
        return []


@st.cache_data(ttl=60)
def load():
    conn = store.connect()
    df = pd.read_sql_query("SELECT * FROM mentions", conn)
    conn.close()
    if not df.empty:
        # format="ISO8601" handles the mix of 'Z' and offset/naive timestamps across sources;
        # without it, pandas infers one format and silently coerces the rest to NaT.
        df["created_at"] = pd.to_datetime(df["created_at"], errors="coerce", utc=True, format="ISO8601")
        df["date"] = df["created_at"].dt.date
        df["themes_list"] = df["themes"].apply(_parse_themes)
        df["source_label"] = df["source"].map(SOURCE_LABELS).fillna(df["source"])
    return df


df = load()
if df.empty:
    st.warning("No data yet.")
    st.stop()

# ---------------- sidebar ----------------
if os.path.exists(LOGO):
    st.sidebar.image(LOGO, width=130)
include_mock = st.sidebar.toggle("Show mock sources", value=False)
all_sources = sorted(df["source"].unique(), key=lambda s: SOURCE_LABELS.get(s, s))
real_sources = sorted(df[df["is_mock"] == 0]["source"].unique())
picked = st.sidebar.multiselect(
    "Sources", options=all_sources,
    default=all_sources if include_mock else real_sources,
    format_func=lambda s: SOURCE_LABELS.get(s, s) + (" · mock" if df[df.source == s]["is_mock"].max() else ""))

view = df[df["source"].isin(picked)].copy()
if not include_mock:
    view = view[view["is_mock"] == 0]

# ---------------- header ----------------
st.title("Voice of Customer")
windowed = view["created_at"].dropna()
windowed = windowed[windowed >= TREND_START]
span = f" · {windowed.min():%b %Y} to {windowed.max():%b %Y}" if len(windowed) else ""
st.caption(f"{len(view):,} mentions from {view['source'].nunique()} places people talk about Pocket{span}")

tab_overview, tab_themes, tab_sources, tab_feed, tab_ops = st.tabs(
    ["Overview", "Themes", "Sources", "Feed", "System & Ops"])

# ================= OVERVIEW =================
with tab_overview:
    total = len(view)
    pos = int((view["sentiment"] == "positive").sum())
    neg = int((view["sentiment"] == "negative").sum())
    rated = view[view["rating"].notna()]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Mentions", f"{total:,}")
    c2.metric("Positive", f"{pos/total*100:.0f}%" if total else "—")
    c3.metric("Negative", f"{neg/total*100:.0f}%" if total else "—")
    c4.metric("Avg rating", f"{rated['rating'].mean():.1f}★" if len(rated) else "—")

    st.subheader("How people feel")
    mix = view["sentiment"].value_counts().reindex(["positive", "neutral", "negative", "mixed"]).fillna(0)
    fig = px.bar(x=mix.values, y=mix.index, orientation="h", color=mix.index, color_discrete_map=SENTIMENT_COLORS)
    fig.update_layout(showlegend=False, height=190, xaxis_title="", yaxis_title="", margin=dict(l=0, r=0, t=6, b=0))
    st.plotly_chart(fig, use_container_width=True)

    st.subheader("Chatter over time")
    ts = view.dropna(subset=["created_at"]).copy()
    ts = ts[ts["created_at"] >= TREND_START]
    if len(ts):
        ts["week"] = ts["created_at"].dt.tz_localize(None).dt.to_period("W").dt.start_time
        trend = ts.groupby(["week", "sentiment"]).size().reset_index(name="n")
        fig2 = px.bar(trend, x="week", y="n", color="sentiment", color_discrete_map=SENTIMENT_COLORS)
        fig2.update_layout(height=320, xaxis_title="", yaxis_title="", legend_title="", margin=dict(l=0, r=0, t=6, b=0))
        st.plotly_chart(fig2, use_container_width=True)

# ================= THEMES =================
with tab_themes:
    exploded = view.explode("themes_list").dropna(subset=["themes_list"])
    if len(exploded):
        st.subheader("What they talk about")
        theme_sent = exploded.groupby(["themes_list", "sentiment"]).size().reset_index(name="n")
        order = exploded["themes_list"].value_counts().index.tolist()
        fig = px.bar(theme_sent, x="n", y="themes_list", color="sentiment", orientation="h",
                     color_discrete_map=SENTIMENT_COLORS, category_orders={"themes_list": order[::-1]})
        fig.update_layout(height=max(300, 26 * len(order)), yaxis_title="", xaxis_title="",
                          legend_title="", margin=dict(l=0, r=0, t=6, b=0))
        st.plotly_chart(fig, use_container_width=True)

        st.subheader("Where it hurts most")
        neg = exploded[exploded.sentiment == "negative"]["themes_list"].value_counts().head(8)
        st.dataframe(neg.rename("complaints"), use_container_width=True)

        st.subheader("Theme health")
        st.caption("Negative **rate** matters as much as volume — a small theme can be almost "
                   "entirely negative. Sort by either column; watch the sample size.")
        min_n = st.number_input("Minimum mentions to show", min_value=1, max_value=100, value=5, step=1,
                                help="Hides tiny themes whose rates are statistically noisy.")
        g = exploded.groupby("themes_list")
        health = pd.DataFrame({
            "mentions": g.size(),
            "positive": g.apply(lambda d: int((d.sentiment == "positive").sum())),
            "neutral": g.apply(lambda d: int((d.sentiment == "neutral").sum())),
            "negative": g.apply(lambda d: int((d.sentiment == "negative").sum())),
            "mixed": g.apply(lambda d: int((d.sentiment == "mixed").sum())),
            "avg confidence": g["confidence"].mean().round(2),
        })
        health["negative rate"] = (health["negative"] / health["mentions"] * 100).round(0)
        health = health.reset_index().rename(columns={"themes_list": "theme"})
        small = health[health["mentions"] < min_n]
        health = health[health["mentions"] >= min_n].sort_values("negative", ascending=False)
        health = health[["theme", "mentions", "positive", "neutral", "negative", "mixed",
                         "negative rate", "avg confidence"]]
        st.dataframe(
            health, use_container_width=True, hide_index=True,
            column_config={
                "negative rate": st.column_config.NumberColumn("negative rate", format="%d%%"),
                "negative": st.column_config.NumberColumn("negative"),
            })
        if len(small):
            st.caption(f"{len(small)} theme(s) hidden with fewer than {min_n} mentions "
                       f"(too small to read a rate into): {', '.join(small['theme'])}.")

# ================= SOURCES =================
with tab_sources:
    st.subheader("Where the chatter comes from")
    by_source = view.groupby(["source_label", "sentiment"]).size().reset_index(name="n")
    fig = px.bar(by_source, x="source_label", y="n", color="sentiment", color_discrete_map=SENTIMENT_COLORS)
    fig.update_layout(height=330, xaxis_title="", yaxis_title="", legend_title="", margin=dict(l=0, r=0, t=6, b=0))
    st.plotly_chart(fig, use_container_width=True)

    score = view.groupby("source_label").agg(
        mentions=("id", "count"),
        positive=("sentiment", lambda g: round((g == "positive").mean() * 100)),
        avg_rating=("rating", lambda r: round(r.mean(), 1)),
    ).reset_index().sort_values("mentions", ascending=False)
    score = score.rename(columns={"source_label": "source", "positive": "% positive", "avg_rating": "avg ★"})
    st.dataframe(score, use_container_width=True, hide_index=True)

# ================= FEED =================
with tab_feed:
    st.caption("The human-audit layer: filter, read the raw words, and sanity-check the model's calls.")
    fc1, fc2, fc3 = st.columns(3)
    sent_filter = fc1.multiselect("Mood", ["positive", "neutral", "negative", "mixed"], [])
    theme_options = sorted({t for lst in view["themes_list"] for t in lst})
    theme_filter = fc2.selectbox("Topic", ["Anything"] + theme_options)
    search = fc3.text_input("Search")

    gc1, gc2 = st.columns([1, 2])
    low_only = gc1.checkbox("Review low-confidence only", value=False,
                            help="Show only the model calls least likely to be right — the audit queue.")
    max_conf = gc2.slider("Maximum confidence", 0.0, 1.0, 0.70, 0.05,
                          disabled=not low_only,
                          help="When 'Review low-confidence only' is on, show rows at or below this confidence.")

    feed = view.copy()
    if sent_filter:
        feed = feed[feed["sentiment"].isin(sent_filter)]
    if theme_filter != "Anything":
        feed = feed[feed["themes_list"].apply(lambda l: theme_filter in l)]
    if search:
        feed = feed[feed["text"].str.contains(search, case=False, na=False)]
    if low_only:
        feed = feed[feed["confidence"].notna() & (feed["confidence"] <= max_conf)]

    feed = feed.sort_values("created_at", ascending=False, na_position="last")
    st.caption(f"{len(feed):,} matching · showing up to 150")
    for _, r in feed.head(150).iterrows():
        dot = SENTIMENT_COLORS.get(r["sentiment"], "#9ca3af")
        mock = " · mock" if r["is_mock"] else ""
        stars = f" · {int(r['rating'])}★" if pd.notna(r["rating"]) else ""
        conf = f" · conf {r['confidence']:.2f}" if pd.notna(r["confidence"]) else " · conf —"
        st.markdown(f"<span style='color:{dot};font-weight:600'>●</span> **{r['source_label']}**{mock} · "
                    f"{r['sentiment']}{stars}{conf}", unsafe_allow_html=True)
        st.write(r["text"][:600] + ("…" if len(str(r["text"])) > 600 else ""))
        tags = " ".join(f"`{t}`" for t in r["themes_list"])
        if pd.notna(r["url"]) and r["url"]:
            tags += f" · [open]({r['url']})"
        if tags.strip():
            st.caption(tags)
        st.divider()

# ================= SYSTEM & OPS =================
with tab_ops:
    real_df = df[df["is_mock"] == 0]
    n_real, n_mock = len(real_df), int((df["is_mock"] == 1).sum())

    # ---- A. Pipeline ----
    st.subheader("Pipeline architecture")
    st.markdown(
        "```text\n"
        "Sources (9)  →  Source-specific collectors  →  Common normalized schema\n"
        "             →  SQLite store + dedup  →  Claude sentiment/theme classification\n"
        "             →  QA & exception review  →  Streamlit dashboard + operational alerts\n"
        "```")
    st.markdown(
        "- **Collectors** turn each platform's raw records into one shared shape.\n"
        "- **Normalized fields:** `source`, `native_id`, `kind`, `author`, `text`, `rating`, "
        "`created_at`, `url`, `lang`, `is_mock`, `collected_at` → then `sentiment`, `themes`, "
        "`confidence`, `classified_at` after classification.\n"
        "- **Dedup:** each row's primary key is a deterministic hash of **`source` + native platform id**, "
        "so re-running a collector never creates duplicates (`INSERT OR IGNORE`).\n"
        "- **Classification:** Claude returns sentiment, 1–3 themes, a relevance judgment, and a confidence. "
        "Streamlit reads the resulting records.")
    st.info("This deployed prototype is **refreshable, not real-time streaming**. It reads a committed "
            "SQLite snapshot; a live build would run collectors + classifier on a schedule into a hosted DB.",
            icon="ℹ️")

    # ---- B. Real vs mock ----
    st.subheader("Sources — real vs mocked")
    counts = df.groupby("source").size()
    src_rows = []
    for s, (status, path) in SOURCE_STATUS.items():
        src_rows.append({"source": SOURCE_LABELS.get(s, s), "status": status,
                         "mentions": int(counts.get(s, 0)),
                         "how it's collected / production path": path})
    src_tbl = pd.DataFrame(src_rows).sort_values(["status", "mentions"], ascending=[True, False])
    st.dataframe(src_tbl, use_container_width=True, hide_index=True)
    st.caption(f"Real prototype data: **{n_real:,}** mentions (App Store, Google Play, Reddit, YouTube). "
               f"Mocked & explicitly labelled: **{n_mock}** (Trustpilot, X, Facebook, Instagram, TikTok). "
               "Mocked rows are excluded from headline numbers unless the sidebar toggle is on — they are "
               "**not** real data.")

    # ---- C. Cadence ----
    st.subheader("Refresh cadence")
    cc1, cc2 = st.columns(2)
    with cc1:
        st.markdown("**Daily**")
        st.markdown("- Collect new reviews & social mentions\n- Deduplicate\n"
                    "- Classify only new / unclassified rows\n- Review urgent negatives")
        st.markdown("**During launches / incidents**")
        st.markdown("- Raise refresh frequency on high-priority sources where the API allows\n"
                    "- Watch volume & negative-sentiment spikes more closely")
    with cc2:
        st.markdown("**Weekly**")
        st.markdown("- Review theme trends & top negatives (count *and* rate)\n"
                    "- Review low-confidence classifications\n"
                    "- Pick product / support / marketing / ops actions; record what changed")
        st.markdown("**Monthly**")
        st.markdown("- Review taxonomy, source coverage, costs, alert thresholds\n"
                    "- Re-check model accuracy against a human-labelled sample")
    st.caption("Actual refresh ability depends on each platform's API constraints.")

    # ---- D. Owner ----
    st.subheader("Owner & operating loop")
    oc1, oc2 = st.columns(2)
    with oc1:
        st.markdown("**Primary owner** — Customer Experience / Support Ops / VoC lead")
        st.markdown("- ~15 min/day on negative & urgent feedback\n"
                    "- Triage support & shipping issues\n"
                    "- Route defects → product/eng, messaging confusion → marketing\n"
                    "- Maintain the pipeline; review classifier quality; weekly summary")
        st.markdown("**Founder** — weekly review of top themes, major spikes, and decisions only "
                    "(should not operate it daily).")
    with oc2:
        st.markdown("**Weekly operating loop**")
        st.markdown("1. Review alerts\n2. Review negative-rate changes\n"
                    "3. Open representative raw comments\n4. Validate classifications\n"
                    "5. Assign actions\n6. Track whether the theme improves after intervention")

    # ---- E. Alerts ----
    st.subheader("Operational alerts")
    st.markdown(
        "- Negative share **> 30%** over a rolling 24h\n"
        "- Daily volume **> 3×** the trailing 7-day average\n"
        "- Any **1★** mentioning *shipping, damaged, refund,* or *no response*\n"
        "- Sudden rise in *device reliability, transcription, shipping,* or *support* complaints\n"
        "- A theme's negative rate rises materially week over week\n"
        "- High-severity mention with **low classifier confidence**\n"
        "- Collector failure / no new data from an expected source\n"
        "- Unprocessed rows sitting in the classification queue")
    st.caption("Thresholds are **starting assumptions** — tune them after observing normal volumes. "
               "(Designed here; not yet wired to Slack.)")

    # ---- F. QA ----
    st.subheader("QA & model governance")
    conf = real_df["confidence"].dropna()
    drift = df["themes_list"].explode().dropna()
    drift_tags = sorted(set(drift) - set(THEME_TAXONOMY))
    drift_rows = int(df["themes_list"].apply(lambda l: any(t not in THEME_TAXONOMY for t in l)).sum())
    q1, q2, q3, q4 = st.columns(4)
    q1.metric("Avg confidence", f"{conf.mean():.2f}" if len(conf) else "—")
    q2.metric("Median confidence", f"{conf.median():.2f}" if len(conf) else "—")
    q3.metric("Below 0.70", f"{(conf < 0.70).mean()*100:.0f}%" if len(conf) else "—")
    q4.metric("Below 0.50", f"{(conf < 0.50).mean()*100:.0f}%" if len(conf) else "—")
    st.caption(f"Real-data confidence, n={len(conf):,}. The model is **not assumed correct** — "
               "these are the numbers that decide how hard we audit.")
    st.markdown(
        "- Human-label a ~50–100 mention holdout; compare human vs model **sentiment** and **theme** labels\n"
        "- Review low-confidence rows (Feed → *Review low-confidence only*)\n"
        "- Use star rating vs predicted sentiment as a weak check on rated sources\n"
        "- Inspect irrelevant \"Pocket\" mentions; keep high-severity low-confidence rows out of aggregate-only views\n"
        "- Revisit prompt/taxonomy if agreement drops below the chosen bar")
    if drift_tags:
        st.caption(f"**Theme drift:** the model coined {len(drift_tags)} tag(s) outside the fixed 16-item "
                   f"taxonomy across {drift_rows} row(s): {', '.join(drift_tags)}. Worth a taxonomy review.")

    # ---- G. Cost ----
    st.subheader("Cost")
    st.caption("Classification is the only variable software cost. Figures are **directional assumptions** — "
               "the formula is shown so they can be checked against live pricing.")
    cost_tbl = pd.DataFrame({
        "item": ["Collection (App Store/Play/Reddit/YouTube)", "Classification — Claude",
                 "Storage", "Hosting", "Operator time"],
        "today (~800/mo)": ["Free tiers / free quota", "~$2 / mo (directional)",
                            "SQLite — ~free", "Streamlit Community Cloud — free",
                            "~15 min/day + weekly review"],
        "10× (~8,000/mo)": ["Mostly free; add mock-source API costs in prod", "~$15–20 / mo (directional)",
                            "Managed Postgres — assume $15–50/mo", "Paid hosting — assume $20–50/mo",
                            "~30 min/day + weekly review"],
    })
    st.dataframe(cost_tbl, use_container_width=True, hide_index=True)
    with st.expander("How the Claude cost is calculated"):
        st.markdown(
            "Batch of **20** mentions/call; each item sends up to 1,200 chars of text (~300 tokens) + "
            "amortized system prompt; output is a small JSON object per item plus extended-thinking tokens.\n\n"
            "```text\n"
            "per item  ≈ ~330 input tokens + ~90 output tokens\n"
            "cost/item ≈ 330×$3/M (in) + 90×$15/M (out)  ≈ $0.0023   [Sonnet-class pricing assumption]\n"
            "800 new/mo  ≈ 800 × $0.0023   ≈ ~$1.8 / mo\n"
            "8,000 new/mo ≈ 8,000 × $0.0023 ≈ ~$18 / mo\n"
            "```\n"
            "Only **new/unclassified** rows are billed (dedup + `WHERE sentiment IS NULL`). Extended-thinking "
            "output adds variance, so treat these as order-of-magnitude, not precise. Mocked sources incur "
            "**no** collection cost today but would in production (paid X/Meta/TikTok/Trustpilot access).")
