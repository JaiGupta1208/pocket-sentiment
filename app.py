"""Pocket — Voice of Customer. Internal dashboard."""
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

st.set_page_config(page_title="Pocket · Voice of Customer", page_icon=LOGO, layout="wide")

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

# Suggested starting points per theme — drafted from what customers actually raise.
# Shown behind a click on the Themes tab; starting points for the team, not decisions.
THEME_ACTIONS = {
    "device_reliability": [
        "Ship a firmware watchdog: auto-recover and notify instead of dying silently mid-recording.",
        "Add a diagnostics screen in the app so support can see what failed without email ping-pong.",
        "Offer proactive replacements for known-bad units. Reliability complaints compound fastest.",
    ],
    "price_value": [
        "Publish a clear free-vs-Pro comparison. Most price complaints read as confusion about what's paid.",
        "Trial month of Pro with the hardware, so the subscription proves its value before it bills.",
        "Reframe marketing around time saved per week, not features. Value objections need an ROI answer.",
    ],
    "comparison_competitor": [
        "Publish an honest Pocket-vs-Plaud/Otter comparison page. Shoppers are building their own on Reddit.",
        "Lean into what's genuinely different (screenless, wearable, on-the-go capture) in ads and listings.",
        "Seed reviews with the creators doing head-to-head comparisons; their videos dominate the search results.",
    ],
    "customer_support": [
        "Set a visible first-response SLA. Most complaints are about silence, not the resolution.",
        "Add order-status and return self-service; a big share of tickets never needed a human.",
        "Staff up support ahead of launches, when ticket volume and public complaints spike together.",
    ],
    "privacy": [
        "Publish a plain-English page on what's recorded, stored, and deletable, and link it from the app.",
        "Add a visible recording indicator and one-tap pause for sensitive moments.",
        "Explain consent norms by region in onboarding; uncertainty here kills word-of-mouth.",
    ],
    "app_experience": [
        "Prioritise search across past recordings. It's the most requested missing feature.",
        "Add folders/tags for organising recordings; heavy users are hitting a wall.",
        "Speed up sync; 'recording exists but won't load' reads as data loss to users.",
    ],
    "shipping_delivery": [
        "Show honest lead times at checkout and email proactively when they slip.",
        "Complaints cluster around launches, so pre-position inventory or cap orders.",
    ],
    "summary_quality": [
        "Add a 'fix this summary' feedback button. Misattributed statements are the sharpest complaint.",
        "Let users edit summaries before sharing; trust rises when they can correct the record.",
    ],
    "transcription_accuracy": [
        "Tune for accents and noisy rooms, where the praised baseline slips.",
        "Custom vocabulary (names, jargon) would fix the most common repeated errors.",
    ],
    "battery_life": [
        "A battery-saver capture mode and clearer battery expectations in marketing.",
    ],
    "magnet_attachment": [
        "Offer a stronger clip/magnet accessory. People are losing devices off their clothes.",
    ],
    "hardware_build": [
        "Tighten QC on casing finish; scratched-on-arrival units drive disproportionate anger.",
    ],
    "ease_of_setup": [
        "Setup is a strength. Feature the '2-minute setup' in listings and ads.",
    ],
}

SEARCH_HINTS = '"Plaud", "subscription", "battery", "magnet", "refund"'


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


@st.cache_data(ttl=60)
def load_weekly():
    conn = store.connect()
    try:
        wk = pd.read_sql_query(
            "SELECT week_start, n, pos, neg, net, summary FROM weekly_summaries ORDER BY week_start", conn)
    except Exception:
        wk = pd.DataFrame()
    conn.close()
    if not wk.empty:
        wk["week_start"] = pd.to_datetime(wk["week_start"])
    return wk


df = load()
if df.empty:
    st.warning("No data yet.")
    st.stop()

# Drop off-topic mentions — a different "pocket" (Firefox Pocket, pocket knives, etc.),
# flagged by the AI relevance pass (relevance.py). NULL/unjudged rows are kept.
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

st.sidebar.divider()
if st.sidebar.button("Refresh data", use_container_width=True,
                     help="Pulls new mentions, checks relevance, tags them, and updates the weekly pulse."):
    import refresh as _refresh
    with st.status("Refreshing. This takes a few minutes...", expanded=True) as _status:
        for step, ok, detail in _refresh.run_refresh(log=lambda m: None):
            st.write(("ok: " if ok else "skipped: ") + f"{step}: {detail}")
        _status.update(label="Refresh finished", state="complete")
    load.clear()
    load_weekly.clear()
    st.sidebar.caption("Done. New data appears on your next click.")
st.sidebar.caption("Designed to run daily. Reddit needs a browser session, so it refreshes manually for now.")

view = df[df["source"].isin(picked)].copy()
if not include_mock:
    view = view[view["is_mock"] == 0]

# ---------------- header ----------------
st.title("Voice of Customer")
windowed = view["created_at"].dropna()
windowed = windowed[windowed >= TREND_START]
span = f" · {windowed.min():%b %Y} to {windowed.max():%b %Y}" if len(windowed) else ""
st.caption(f"{len(view):,} mentions from {view['source'].nunique()} places people talk about Pocket{span}")

tab_overview, tab_themes, tab_sources, tab_feed, tab_pulse = st.tabs(
    ["Overview", "Themes", "Sources", "Feed", "Weekly pulse"])

# ================= OVERVIEW =================
with tab_overview:
    # ---- The read: conclusions first, computed live from the data ----
    def _posrate(d):
        return (d["sentiment"] == "positive").mean() * 100 if len(d) else None
    insights = []
    buyers = view[view["source"].isin(["appstore", "play"])]
    disc = view[view["source"].isin(["reddit", "youtube"])]
    bp, dp = _posrate(buyers), _posrate(disc)
    if bp is not None and dp is not None and len(buyers) >= 20 and len(disc) >= 20 and bp - dp >= 10:
        insights.append(f"People who own it are happy: app-store reviewers run {bp:.0f}% positive. "
                        f"The wider conversation on Reddit and YouTube, much of it people still deciding "
                        f"whether to buy, runs {dp:.0f}%.")
    expl0 = view.explode("themes_list").dropna(subset=["themes_list"])
    if len(expl0):
        tg = expl0.groupby("themes_list")
        tt = pd.DataFrame({"n": tg.size(), "neg": tg.apply(lambda d: int((d["sentiment"] == "negative").sum()))})
        tt["rate"] = tt["neg"] / tt["n"] * 100
        big = tt[tt["n"] >= 10]
        if len(big):
            w = big.sort_values("rate", ascending=False).iloc[0]
            insights.append(f"The sorest subject is {w.name.replace('_', ' ')}: when it comes up, "
                            f"{w['rate']:.0f}% of the time it's a complaint ({int(w['n'])} mentions).")
            loud = big.sort_values("neg", ascending=False).iloc[0]
            if loud.name != w.name:
                insights.append(f"{loud.name.replace('_', ' ').capitalize()} draws the most complaints "
                                f"outright, with {int(loud['neg'])} negative mentions.")
    if insights:
        with st.container(border=True):
            st.markdown("**The read**")
            for line in insights[:3]:
                st.markdown(f"- {line}")
    with st.expander("How comments get labelled"):
        st.markdown(
            "An AI model reads every comment and tags it **positive, negative, neutral or mixed**, plus "
            "the topics it touches. \"Negative\" means the person is describing a problem or "
            "disappointment in their own words. It isn't a star-rating cutoff or a keyword count.\n\n"
            "So when a topic shows \"72% negative\", it means 72% of the *comments that mention it* are "
            "complaints. That's a share of the conversation, **not** a product failure rate.\n\n"
            "Every tag carries a confidence score, and the least-sure calls are surfaced in the Feed "
            "for a human to check. Comments about a different \"pocket\" (the Firefox app, pocket "
            "knives...) are detected and left out entirely.")

    total = len(view)
    pos = int((view["sentiment"] == "positive").sum())
    neg = int((view["sentiment"] == "negative").sum())
    rated = view[view["rating"].notna()]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Mentions", f"{total:,}")
    c2.metric("Positive", f"{pos/total*100:.0f}%" if total else "n/a")
    c3.metric("Negative", f"{neg/total*100:.0f}%" if total else "n/a")
    c4.metric("Avg rating", f"{rated['rating'].mean():.1f}★" if len(rated) else "n/a")

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
        # ---- The big issues: what people say, and what could be done about it ----
        st.subheader("The big issues")
        st.caption("Ranked by how much they hurt: how many complaints, and how one-sided the "
                   "conversation is. Open one to read real comments and a suggested fix.")
        g0 = exploded.groupby("themes_list")
        q = pd.DataFrame({"mentions": g0.size(),
                          "negatives": g0.apply(lambda d: int((d["sentiment"] == "negative").sum()))})
        q["rate"] = (q["negatives"] / q["mentions"] * 100).round(0)
        q = q[(q["mentions"] >= 8) & (q["negatives"] >= 5)].reset_index().rename(columns={"themes_list": "theme"})
        q["priority"] = q["negatives"] * q["rate"]
        for _, row in q.sort_values("priority", ascending=False).head(5).iterrows():
            label = row["theme"].replace("_", " ")
            header = (f"{label}: {int(row['negatives'])} of {int(row['mentions'])} comments "
                      f"that mention it are negative ({int(row['rate'])}%)")
            with st.expander(header):
                cand = view[(view["sentiment"] == "negative")
                            & view["themes_list"].apply(lambda l, t=row["theme"]: t in l)]
                cand = cand[cand["text"].str.len() >= 60].sort_values("confidence", ascending=False)
                seen_sources, shown = set(), 0
                st.markdown("**In their words**")
                for _, c in cand.iterrows():
                    if c["source"] in seen_sources and shown < len(cand) - 1:
                        continue
                    quote = str(c["text"]).strip().replace("\n", " ")[:260]
                    st.caption(f"“{quote}…” ({c['source_label']})")
                    seen_sources.add(c["source"]); shown += 1
                    if shown == 2:
                        break
                actions = THEME_ACTIONS.get(row["theme"])
                if actions:
                    st.markdown("**What could Pocket do about it**")
                    for a in actions:
                        st.markdown(f"- {a}")
                    st.caption("Drafted from the comments above. Starting points for the team, not decisions.")

        st.subheader("What they talk about")
        theme_sent = exploded.groupby(["themes_list", "sentiment"]).size().reset_index(name="n")
        order = exploded["themes_list"].value_counts().index.tolist()
        fig = px.bar(theme_sent, x="n", y="themes_list", color="sentiment", orientation="h",
                     color_discrete_map=SENTIMENT_COLORS, category_orders={"themes_list": order[::-1]})
        fig.update_layout(height=max(300, 26 * len(order)), yaxis_title="", xaxis_title="",
                          legend_title="", margin=dict(l=0, r=0, t=6, b=0))
        st.plotly_chart(fig, use_container_width=True)

        st.subheader("Theme health")
        st.caption("Rate matters as much as volume: a small theme can be almost all negative.")
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
    st.caption("Worth knowing when you read this: App Store and Google Play are mostly verified owners "
               "writing reviews, while Reddit and YouTube skew toward people still deciding whether to "
               "buy. That's why the numbers differ so sharply, and that gap is the most useful thing "
               "on this page.")

# ================= FEED =================
with tab_feed:
    st.caption("The raw comments behind every number. Filter, search, and check the AI's calls.")
    fc1, fc2, fc3 = st.columns(3)
    sent_filter = fc1.multiselect("Mood", ["positive", "neutral", "negative", "mixed"], [])
    theme_options = sorted({t for lst in view["themes_list"] for t in lst})
    theme_filter = fc2.selectbox("Topic", ["Anything"] + theme_options)
    search = fc3.text_input("Search", placeholder="e.g. Plaud, subscription, battery...")
    st.caption(f"Try searching {SEARCH_HINTS}, or a competitor, a feature, or a complaint in "
               "the customer's own words.")

    gc1, gc2 = st.columns([1, 2])
    low_only = gc1.checkbox("Only the AI's least-sure calls", value=False)
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
        conf = f" · conf {r['confidence']:.2f}" if pd.notna(r["confidence"]) else " · conf n/a"
        st.markdown(f"<span style='color:{dot};font-weight:600'>●</span> **{r['source_label']}**{mock} · "
                    f"{r['sentiment']}{stars}{conf}", unsafe_allow_html=True)
        st.write(r["text"][:600] + ("…" if len(str(r["text"])) > 600 else ""))
        tags = " ".join(f"`{t}`" for t in r["themes_list"])
        if pd.notna(r["url"]) and r["url"]:
            tags += f" · [open]({r['url']})"
        if tags.strip():
            st.caption(tags)
        st.divider()

# ================= WEEKLY PULSE =================
with tab_pulse:
    wk = load_weekly()
    st.caption("One sentiment score per week, so a launch, a price change or a marketing push shows "
               "up as movement, not anecdotes. Score = % positive minus % negative that week.")
    if wk.empty:
        st.info("No weekly data yet. Run a refresh to build it.")
    else:
        latest, prev = wk.iloc[-1], (wk.iloc[-2] if len(wk) > 1 else None)
        m1, m2, m3 = st.columns(3)
        m1.metric("Latest week", f"{latest['net']:+.0f}",
                  delta=f"{latest['net'] - prev['net']:+.0f} vs prior week" if prev is not None else None)
        m2.metric("Mentions that week", int(latest["n"]),
                  delta=int(latest["n"] - prev["n"]) if prev is not None else None)
        best = wk.loc[wk["net"].idxmax()]
        m3.metric("Best week so far", f"{best['net']:+.0f}", delta=f"{best['week_start']:%b %d}",
                  delta_color="off")

        figp = px.line(wk, x="week_start", y="net", markers=True)
        figp.add_hline(y=0, line_color="#cbcbcb")
        figp.update_traces(line_color="#4338ca")
        figp.update_layout(height=300, xaxis_title="", yaxis_title="net sentiment",
                           margin=dict(l=0, r=0, t=6, b=0))
        st.plotly_chart(figp, use_container_width=True)
        figv = px.bar(wk, x="week_start", y="n")
        figv.update_traces(marker_color="#c7c9d9")
        figv.update_layout(height=140, xaxis_title="", yaxis_title="mentions",
                           margin=dict(l=0, r=0, t=6, b=0))
        st.plotly_chart(figv, use_container_width=True)

        st.subheader("Week by week")
        with_sum = wk.dropna(subset=["summary"]).sort_values("week_start", ascending=False)
        for _, w in with_sum.head(6).iterrows():
            st.markdown(f"**Week of {w['week_start']:%b %d}** · net {w['net']:+.0f} · {int(w['n'])} mentions")
            st.write(w["summary"])
            st.divider()
        older = with_sum.iloc[6:]
        if len(older):
            with st.expander(f"Earlier weeks ({len(older)})"):
                for _, w in older.iterrows():
                    st.markdown(f"**Week of {w['week_start']:%b %d}** · net {w['net']:+.0f} · {int(w['n'])} mentions")
                    st.write(w["summary"])
                    st.divider()
        st.caption("Summaries are written by the AI model from that week's comments at refresh time. "
                   "Refresh from the sidebar; designed to run daily on a schedule in production.")
