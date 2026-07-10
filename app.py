"""Pocket — Voice of Customer dashboard (Task 3).

Reads the SQLite store the collectors + classifier write to, and presents five views:
Overview, Themes, Sources, Feed, and Pipeline & Ops. Mock sources are badged and kept
out of headline numbers by default.
"""
import json
import os
import pandas as pd
import plotly.express as px
import streamlit as st

import store

st.set_page_config(page_title="Pocket — Voice of Customer", page_icon="🎙️", layout="wide")

SENTIMENT_COLORS = {"positive": "#16a34a", "neutral": "#9ca3af", "negative": "#dc2626", "mixed": "#f59e0b"}
SOURCE_LABELS = {
    "appstore": "App Store", "play": "Google Play", "reddit": "Reddit", "youtube": "YouTube",
    "trustpilot": "Trustpilot", "x": "X / Twitter", "facebook": "Facebook",
    "instagram": "Instagram", "tiktok": "TikTok",
}


@st.cache_data(ttl=300)
def load():
    conn = store.connect()
    df = pd.read_sql_query("SELECT * FROM mentions", conn)
    try:
        method = conn.execute("SELECT v FROM meta WHERE k='classifier_method'").fetchone()
        method = method[0] if method else "unknown"
    except Exception:
        method = "unknown"
    conn.close()
    if not df.empty:
        df["created_at"] = pd.to_datetime(df["created_at"], errors="coerce", utc=True)
        df["date"] = df["created_at"].dt.date
        df["themes_list"] = df["themes"].apply(lambda s: json.loads(s) if s else [])
        df["source_label"] = df["source"].map(SOURCE_LABELS).fillna(df["source"])
    return df, method


df, method = load()
if df.empty:
    st.warning("No data yet. Run the collectors and classifier first (see README).")
    st.stop()

# ---------------- sidebar ----------------
st.sidebar.title("🎙️ Pocket VoC")
st.sidebar.caption("Voice-of-customer across the places people talk about Pocket.")

include_mock = st.sidebar.toggle("Include mock sources", value=False,
                                 help="X, Facebook, Instagram, TikTok and Trustpilot are labeled mocks in this build. Off by default so headline numbers use real data only.")
all_sources = sorted(df["source"].unique(), key=lambda s: SOURCE_LABELS.get(s, s))
real_sources = sorted(df[df["is_mock"] == 0]["source"].unique())
default_sources = all_sources if include_mock else real_sources
picked = st.sidebar.multiselect("Sources", options=all_sources,
                                default=default_sources,
                                format_func=lambda s: SOURCE_LABELS.get(s, s) + (" (mock)" if df[df.source == s]["is_mock"].max() else ""))

view = df[df["source"].isin(picked)].copy()
if not include_mock:
    view = view[view["is_mock"] == 0]

st.sidebar.markdown("---")
st.sidebar.metric("Mentions in view", len(view))
st.sidebar.caption(f"Classifier: **{method}**"
                   + ("  \n⚠️ rule-based fallback — add an Anthropic key and re-run `classify.py` for the Claude pass."
                      if method == "rules" else ""))

# ---------------- header ----------------
st.title("Pocket — Voice of Customer")
real_n = int((view["is_mock"] == 0).sum())
mock_n = int((view["is_mock"] == 1).sum())
dates = view["date"].dropna()
st.caption(f"{real_n} real mentions"
           + (f" · {mock_n} mock (labeled)" if mock_n else "")
           + f" · {view['source'].nunique()} sources · "
           + (f"{dates.min()} → {dates.max()}" if len(dates) else "no dates"))

tab_overview, tab_themes, tab_sources, tab_feed, tab_ops = st.tabs(
    ["Overview", "Themes", "Sources", "Feed", "Pipeline & Ops"])

# ================= OVERVIEW =================
with tab_overview:
    c1, c2, c3, c4 = st.columns(4)
    sent_counts = view["sentiment"].value_counts()
    total = len(view)
    pos = int(sent_counts.get("positive", 0))
    neg = int(sent_counts.get("negative", 0))
    c1.metric("Total mentions", total)
    c2.metric("Positive", f"{pos/total*100:.0f}%" if total else "—")
    c3.metric("Negative", f"{neg/total*100:.0f}%" if total else "—")
    rated = view[view["rating"].notna()]
    c4.metric("Avg star rating", f"{rated['rating'].mean():.2f}⭐" if len(rated) else "—",
              help="App Store + Google Play + Trustpilot only")

    st.markdown("#### Sentiment mix")
    mix = view["sentiment"].value_counts().reindex(["positive", "neutral", "negative", "mixed"]).fillna(0)
    fig = px.bar(x=mix.values, y=mix.index, orientation="h",
                 color=mix.index, color_discrete_map=SENTIMENT_COLORS)
    fig.update_layout(showlegend=False, height=200, xaxis_title="mentions", yaxis_title="",
                      margin=dict(l=0, r=0, t=10, b=0))
    st.plotly_chart(fig, use_container_width=True)

    st.markdown("#### Volume & sentiment over time")
    ts = view.dropna(subset=["date"]).copy()
    if len(ts):
        ts["week"] = pd.to_datetime(ts["date"]).dt.to_period("W").dt.start_time
        trend = ts.groupby(["week", "sentiment"]).size().reset_index(name="n")
        fig2 = px.bar(trend, x="week", y="n", color="sentiment",
                      color_discrete_map=SENTIMENT_COLORS)
        fig2.update_layout(height=320, xaxis_title="", yaxis_title="mentions",
                           legend_title="", margin=dict(l=0, r=0, t=10, b=0))
        st.plotly_chart(fig2, use_container_width=True)
    else:
        st.info("No usable timestamps in the current selection.")

# ================= THEMES =================
with tab_themes:
    st.markdown("#### What people talk about")
    exploded = view.explode("themes_list").dropna(subset=["themes_list"])
    if len(exploded):
        theme_sent = exploded.groupby(["themes_list", "sentiment"]).size().reset_index(name="n")
        order = exploded["themes_list"].value_counts().index.tolist()
        fig = px.bar(theme_sent, x="n", y="themes_list", color="sentiment", orientation="h",
                     color_discrete_map=SENTIMENT_COLORS,
                     category_orders={"themes_list": order[::-1]})
        fig.update_layout(height=max(320, 26 * len(order)), yaxis_title="", xaxis_title="mentions",
                          legend_title="", margin=dict(l=0, r=0, t=10, b=0))
        st.plotly_chart(fig, use_container_width=True)

        st.markdown("#### Most negative themes (fix these first)")
        neg_by_theme = (exploded[exploded.sentiment == "negative"]["themes_list"]
                        .value_counts().head(8))
        st.dataframe(neg_by_theme.rename("negative mentions"), use_container_width=True)
    else:
        st.info("No themes assigned yet.")

# ================= SOURCES =================
with tab_sources:
    st.markdown("#### Volume by source")
    by_source = view.groupby(["source_label", "sentiment"]).size().reset_index(name="n")
    fig = px.bar(by_source, x="source_label", y="n", color="sentiment",
                 color_discrete_map=SENTIMENT_COLORS)
    fig.update_layout(height=340, xaxis_title="", yaxis_title="mentions", legend_title="",
                      margin=dict(l=0, r=0, t=10, b=0))
    st.plotly_chart(fig, use_container_width=True)

    st.markdown("#### Source scorecard")
    def pct_pos(g):
        return (g == "positive").mean() * 100
    score = view.groupby("source_label").agg(
        mentions=("id", "count"),
        pct_positive=("sentiment", pct_pos),
        avg_rating=("rating", "mean"),
        mock=("is_mock", "max"),
    ).reset_index()
    score["pct_positive"] = score["pct_positive"].round(0)
    score["avg_rating"] = score["avg_rating"].round(2)
    score["mock"] = score["mock"].map({1: "mock", 0: "real"})
    st.dataframe(score.sort_values("mentions", ascending=False), use_container_width=True, hide_index=True)

# ================= FEED =================
with tab_feed:
    st.markdown("#### Raw mentions")
    fc1, fc2, fc3 = st.columns(3)
    sent_filter = fc1.multiselect("Sentiment", ["positive", "neutral", "negative", "mixed"], [])
    theme_options = sorted({t for lst in view["themes_list"] for t in lst})
    theme_filter = fc2.selectbox("Theme", ["(any)"] + theme_options)
    search = fc3.text_input("Search text")

    feed = view.copy()
    if sent_filter:
        feed = feed[feed["sentiment"].isin(sent_filter)]
    if theme_filter != "(any)":
        feed = feed[feed["themes_list"].apply(lambda l: theme_filter in l)]
    if search:
        feed = feed[feed["text"].str.contains(search, case=False, na=False)]

    feed = feed.sort_values("created_at", ascending=False, na_position="last")
    st.caption(f"{len(feed)} mentions")
    for _, r in feed.head(150).iterrows():
        badge = SENTIMENT_COLORS.get(r["sentiment"], "#9ca3af")
        mock_tag = " · `MOCK`" if r["is_mock"] else ""
        themes = " ".join(f"`{t}`" for t in r["themes_list"])
        header = (f"<span style='color:{badge};font-weight:600'>●</span> "
                  f"**{r['source_label']}**{mock_tag} · {r['sentiment']} "
                  f"{'· ' + str(int(r['rating'])) + '⭐' if pd.notna(r['rating']) else ''}")
        st.markdown(header, unsafe_allow_html=True)
        st.write(r["text"][:600] + ("…" if len(str(r["text"])) > 600 else ""))
        meta = themes
        if pd.notna(r["url"]) and r["url"]:
            meta += f" · [source]({r['url']})"
        st.caption(meta)
        st.markdown("---")

# ================= OPS =================
with tab_ops:
    st.markdown("#### Pipeline")
    st.markdown("""
```
 Collectors (one per source)              Store            Logic              Dashboard
 ─────────────────────────────           ───────         ───────            ───────────
 App Store  reviews  (HTML/JSON)  ┐
 Google Play reviews (scraper)    │
 Reddit posts+comments (browser)  ├──►  SQLite (dedup) ──► Claude ──►  Streamlit (this app)
 YouTube comments  (Data API v3)  │      mentions tbl      sentiment      Overview / Themes /
 Trustpilot* / X* / Meta* / TikTok*┘     common schema     + themes       Sources / Feed
                                                            + confidence
 * labeled MOCK in this build (see README for why + the production path)
```
""")
    colA, colB = st.columns(2)
    with colA:
        st.markdown("**Refresh cadence**")
        st.markdown("- Reviews (App Store/Play/Trustpilot): **daily**\n"
                    "- Social (Reddit/YouTube/X/TikTok): **daily**, hourly during launches\n"
                    "- Classifier runs on new rows only (dedup by id)")
        st.markdown("**Owner**")
        st.markdown("- 15 min/day: skim negative feed, triage flagged issues\n"
                    "- Weekly: founder reads the Themes tab, picks one fix")
    with colB:
        st.markdown("**Alerts**")
        st.markdown("- Slack ping if negative-share > 30% in a rolling 24h window\n"
                    "- Ping on any 1★ review mentioning `shipping` or `damaged`\n"
                    "- Spike alert if daily volume > 3× trailing-7-day average")
        st.markdown("**Cost** (classifier = the only variable cost)")
        st.dataframe(pd.DataFrame({
            "scenario": ["Today (~800 new/mo)", "10× (~8k/mo)"],
            "Claude cost/mo*": ["< $1", "~$5–8"],
        }), hide_index=True, use_container_width=True)
        st.caption("*Batched ~20 items/call, Claude Sonnet input-dominated. APIs used are free tiers "
                   "(App Store/Play/Reddit) or free quota (YouTube). Hosting: Streamlit Community Cloud (free).")

st.markdown("---")
st.caption("Built for Pocket case study · Task 3. Real data: App Store, Google Play, Reddit, YouTube. "
           "Mock (labeled): Trustpilot, X, Facebook, Instagram, TikTok.")
