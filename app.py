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

# Drop off-topic mentions — a different "pocket" (Firefox Pocket, pocket knives, etc.),
# flagged by the Claude relevance pass (relevance.py). NULL/unjudged rows are kept.
off_topic_n = 0
if "relevant" in df.columns:
    off_topic_n = int((df["relevant"] == 0).sum())
    df = df[df["relevant"] != 0].copy()

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
    # ---- What matters: the read, computed from the data (conclusions before charts) ----
    def _posrate(d):
        return (d["sentiment"] == "positive").mean() * 100 if len(d) else None
    insights = []
    buyers = view[view["source"].isin(["appstore", "play"])]
    disc = view[view["source"].isin(["reddit", "youtube"])]
    bp, dp = _posrate(buyers), _posrate(disc)
    if bp is not None and dp is not None and len(buyers) >= 20 and len(disc) >= 20 and bp - dp >= 10:
        insights.append(f"Owners rate it higher than prospects do: reviewers are {bp:.0f}% positive, "
                        f"versus {dp:.0f}% on Reddit and YouTube.")
    expl0 = view.explode("themes_list").dropna(subset=["themes_list"])
    if len(expl0):
        tg = expl0.groupby("themes_list")
        tt = pd.DataFrame({"n": tg.size(), "neg": tg.apply(lambda d: int((d["sentiment"] == "negative").sum()))})
        tt["rate"] = tt["neg"] / tt["n"] * 100
        big = tt[tt["n"] >= 10]
        if len(big):
            w = big.sort_values("rate", ascending=False).iloc[0]
            insights.append(f"Highest failure rate: {w.name.replace('_', ' ')}, at {w['rate']:.0f}% negative "
                            f"across {int(w['n'])} mentions.")
            loud = big.sort_values("neg", ascending=False).iloc[0]
            if loud.name != w.name:
                insights.append(f"Most complaints by volume: {loud.name.replace('_', ' ')} "
                                f"({int(loud['neg'])} negative).")
    if insights:
        with st.container(border=True):
            st.markdown("**The read**")
            for line in insights[:3]:
                st.markdown(f"- {line}")

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
        # ---- Fix first: reach (how many) vs severity (how negative) ----
        st.subheader("Fix first")
        g0 = exploded.groupby("themes_list")
        q = pd.DataFrame({"mentions": g0.size(),
                          "negatives": g0.apply(lambda d: int((d["sentiment"] == "negative").sum()))})
        q["negative rate"] = (q["negatives"] / q["mentions"] * 100).round(0)
        q = q[(q["mentions"] >= 8) & (q["negatives"] >= 5)].reset_index().rename(columns={"themes_list": "theme"})
        if len(q):
            q["label"] = q["theme"].str.replace("_", " ")
            fig0 = px.scatter(q, x="mentions", y="negative rate", size="negatives", text="label",
                              color="negative rate", color_continuous_scale="Reds", size_max=42)
            fig0.update_traces(textposition="top center", cliponaxis=False)
            fig0.add_vline(x=q["mentions"].median(), line_dash="dot", line_color="#cbcbcb")
            fig0.add_hline(y=50, line_dash="dot", line_color="#cbcbcb")
            fig0.update_layout(height=420, xaxis_title="how many people mention it →",
                               yaxis_title="% negative ↑", coloraxis_showscale=False,
                               margin=dict(l=0, r=0, t=6, b=0))
            st.plotly_chart(fig0, use_container_width=True)
            st.caption("Themes toward the top-right are mentioned often and are mostly negative. "
                       "Bubble size is the number of negative mentions.")
            q["priority"] = q["negatives"] * q["negative rate"]
            for _, row in q.sort_values("priority", ascending=False).head(3).iterrows():
                st.markdown(f"**{row['label']}** — {int(row['negatives'])} negative "
                            f"({int(row['negative rate'])}% of its mentions)")
                cand = view[(view["sentiment"] == "negative")
                            & view["themes_list"].apply(lambda l: row["theme"] in l)]
                cand = cand.sort_values("confidence", ascending=False)
                if len(cand):
                    quote = str(cand.iloc[0]["text"]).strip().replace("\n", " ")[:200]
                    st.caption(f"“{quote}…” — {cand.iloc[0]['source_label']}")

        st.subheader("What they talk about")
        theme_sent = exploded.groupby(["themes_list", "sentiment"]).size().reset_index(name="n")
        order = exploded["themes_list"].value_counts().index.tolist()
        fig = px.bar(theme_sent, x="n", y="themes_list", color="sentiment", orientation="h",
                     color_discrete_map=SENTIMENT_COLORS, category_orders={"themes_list": order[::-1]})
        fig.update_layout(height=max(300, 26 * len(order)), yaxis_title="", xaxis_title="",
                          legend_title="", margin=dict(l=0, r=0, t=6, b=0))
        st.plotly_chart(fig, use_container_width=True)

        st.subheader("Theme health")
        st.caption("Rate matters as much as volume — a small theme can be almost all negative.")
        min_n = st.number_input("Minimum mentions to show", min_value=1, max_value=100, value=5, step=1)
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
            st.caption(f"Hidden (under {min_n} mentions, too small to trust): {', '.join(small['theme'])}.")

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
    st.caption("Read the actual comments and check the model's calls.")
    fc1, fc2, fc3 = st.columns(3)
    sent_filter = fc1.multiselect("Mood", ["positive", "neutral", "negative", "mixed"], [])
    theme_options = sorted({t for lst in view["themes_list"] for t in lst})
    theme_filter = fc2.selectbox("Topic", ["Anything"] + theme_options)
    search = fc3.text_input("Search")

    gc1, gc2 = st.columns([1, 2])
    low_only = gc1.checkbox("Only the model's least-sure calls", value=False)
    max_conf = gc2.slider("Maximum confidence", 0.0, 1.0, 0.70, 0.05, disabled=not low_only)

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
    st.subheader("How a comment gets here")
    st.markdown(
        "```text\n"
        "9 sources  →  a collector per source  →  one shared format\n"
        "           →  SQLite + dedup  →  Claude tags sentiment & theme\n"
        "           →  quick QA  →  this dashboard + alerts\n"
        "```")
    st.markdown(
        "- Each source has its own collector; they all output the same fields, so nothing downstream cares "
        "where a comment came from.\n"
        "- Every row's id is a hash of **source + the platform's own id**, so re-running a collector can't "
        "create duplicates.\n"
        "- Claude then tags each one with sentiment, up to three themes, and a confidence.")
    st.info("It's a snapshot you refresh, not a live stream — right now it reads a saved database. "
            "A production version would run the collectors and Claude on a schedule.", icon="ℹ️")

    # ---- B. Real vs mock ----
    st.subheader("What's real, what's mocked")
    counts = df.groupby("source").size()
    src_rows = []
    for s, (status, path) in SOURCE_STATUS.items():
        src_rows.append({"source": SOURCE_LABELS.get(s, s), "status": status,
                         "mentions": int(counts.get(s, 0)),
                         "how it's collected / production path": path})
    src_tbl = pd.DataFrame(src_rows).sort_values(["status", "mentions"], ascending=[True, False])
    st.dataframe(src_tbl, use_container_width=True, hide_index=True)
    st.caption(f"{n_real:,} real (App Store, Google Play, Reddit, YouTube) · {n_mock} mocked and labelled "
               "(Trustpilot, X, Facebook, Instagram, TikTok). Mocked rows stay out of the headline numbers "
               "unless you toggle them on.")
    if off_topic_n:
        st.caption(f"Data quality: a relevance check removed **{off_topic_n}** off-topic mentions before "
                   "anything you see here — a different “pocket” (Firefox Pocket, pocket knives, "
                   "generic workflow talk), mostly from Reddit. “Pocket” is a noisy search term, so "
                   "each mention is checked for whether it's actually about this product.")

    # ---- C. Cadence ----
    st.subheader("How often it updates")
    cc1, cc2 = st.columns(2)
    with cc1:
        st.markdown("**Every day**")
        st.markdown("- Pull new mentions, dedupe, tag the new ones\n- Skim the urgent negatives")
        st.markdown("**During a launch or incident**")
        st.markdown("- Pull the hot sources more often (where the API lets us)\n- Watch for spikes")
    with cc2:
        st.markdown("**Every week**")
        st.markdown("- Look at theme trends and top negatives — by count *and* rate\n"
                    "- Check the low-confidence calls\n- Pick something to act on, note what changed")
        st.markdown("**Every month**")
        st.markdown("- Revisit the themes, sources, cost, and alert levels\n"
                    "- Re-check accuracy against a hand-labelled sample")
    st.caption("How often we can actually pull depends on each platform's API.")

    # ---- D. Owner ----
    st.subheader("Who runs it")
    oc1, oc2 = st.columns(2)
    with oc1:
        st.markdown("**Day to day** — a Customer Experience / Support lead")
        st.markdown("- ~15 min a day on the negatives\n- Sends defects to product, messaging gaps to marketing\n"
                    "- Keeps the pipeline running and spot-checks the model")
        st.markdown("**The founder** dips in weekly for the big themes and decisions — not every day.")
    with oc2:
        st.markdown("**The weekly loop**")
        st.markdown("1. Check alerts\n2. See which negatives are rising\n3. Read a few real comments\n"
                    "4. Sanity-check the tags\n5. Assign an action\n6. See if it improved next week")

    # ---- E. Alerts ----
    st.subheader("What sets off an alert")
    st.markdown(
        "- Negatives cross **30%** in a day\n"
        "- Volume jumps past **3×** the usual week\n"
        "- A **1★** mentions *shipping, damaged, refund,* or *no response*\n"
        "- Complaints about *reliability, transcription, shipping,* or *support* suddenly climb\n"
        "- A theme gets sharply more negative week over week\n"
        "- Something serious comes in that the model wasn't sure about\n"
        "- A collector breaks, or a source goes quiet")
    st.caption("These are starting points — we'd tune them once we know what normal looks like. "
               "Designed, not yet wired to Slack.")

    # ---- F. QA ----
    st.subheader("Keeping the model honest")
    conf = real_df["confidence"].dropna()
    drift = df["themes_list"].explode().dropna()
    drift_tags = sorted(set(drift) - set(THEME_TAXONOMY))
    drift_rows = int(df["themes_list"].apply(lambda l: any(t not in THEME_TAXONOMY for t in l)).sum())
    q1, q2, q3, q4 = st.columns(4)
    q1.metric("Avg confidence", f"{conf.mean():.2f}" if len(conf) else "—")
    q2.metric("Median confidence", f"{conf.median():.2f}" if len(conf) else "—")
    q3.metric("Below 0.70", f"{(conf < 0.70).mean()*100:.0f}%" if len(conf) else "—")
    q4.metric("Below 0.50", f"{(conf < 0.50).mean()*100:.0f}%" if len(conf) else "—")
    st.caption(f"Confidence is the model's own certainty in each call (n={len(conf):,}) — a signal for what to "
               "double-check, not a measured accuracy.")
    st.markdown(
        "- Hand-label ~50–100 mentions and compare against the model to get a real accuracy read\n"
        "- Work the low-confidence queue in the Feed\n"
        "- Cross-check star ratings against predicted sentiment where we have stars\n"
        "- Don't let a serious-but-unsure comment vanish into an aggregate")
    if drift_tags:
        st.caption(f"The model coined {len(drift_tags)} tag(s) outside the 16 set themes across "
                   f"{drift_rows} row(s): {', '.join(drift_tags)} — worth a taxonomy look.")

    # ---- G. Cost ----
    st.subheader("What it costs")
    st.caption("Tagging with Claude is the only thing that costs money. Numbers are directional — the maths is below.")
    cost_tbl = pd.DataFrame({
        "item": ["Collecting (App Store/Play/Reddit/YouTube)", "Tagging with Claude",
                 "Storage", "Hosting", "Someone to run it"],
        "today (~800/mo)": ["Free", "~$2 / mo", "SQLite — free", "Streamlit — free", "~15 min/day"],
        "10× (~8,000/mo)": ["Free; paid access for mocked sources in prod", "~$15–20 / mo",
                            "Postgres — ~$15–50/mo", "Paid host — ~$20–50/mo", "~30 min/day"],
    })
    st.dataframe(cost_tbl, use_container_width=True, hide_index=True)
    with st.expander("The maths behind the Claude cost"):
        st.markdown(
            "20 mentions per call, ~300 tokens of text each. Only new mentions get billed.\n\n"
            "```text\n"
            "per item  ≈ 330 in + 90 out tokens ≈ $0.0023   (Sonnet-class pricing, an assumption)\n"
            "800/mo    ≈ ~$1.8/mo\n"
            "8,000/mo  ≈ ~$18/mo\n"
            "```\n"
            "Treat these as ballpark. Mocked sources cost nothing today but would need paid access in production.")
