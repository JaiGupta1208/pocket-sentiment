"""Pocket — Voice of Customer dashboard (Task 3)."""
import json
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


@st.cache_data(ttl=60)
def load():
    conn = store.connect()
    df = pd.read_sql_query("SELECT * FROM mentions", conn)
    conn.close()
    if not df.empty:
        df["created_at"] = pd.to_datetime(df["created_at"], errors="coerce", utc=True)
        df["date"] = df["created_at"].dt.date
        df["themes_list"] = df["themes"].apply(lambda s: json.loads(s) if s else [])
        df["source_label"] = df["source"].map(SOURCE_LABELS).fillna(df["source"])
    return df


df = load()
if df.empty:
    st.warning("No data yet.")
    st.stop()

# ---------------- sidebar ----------------
st.sidebar.title("🎙️ Pocket")
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
st.title("Pocket — Voice of Customer")
dates = view["date"].dropna()
span = f" · {dates.min():%b %d} to {dates.max():%b %d}" if len(dates) else ""
st.caption(f"{len(view):,} mentions from {view['source'].nunique()} places people talk about Pocket{span}")

tab_overview, tab_themes, tab_sources, tab_feed = st.tabs(["Overview", "Themes", "Sources", "Feed"])

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
    ts = view.dropna(subset=["date"]).copy()
    if len(ts):
        ts["week"] = pd.to_datetime(ts["date"]).dt.to_period("W").dt.start_time
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
    fc1, fc2, fc3 = st.columns(3)
    sent_filter = fc1.multiselect("Mood", ["positive", "neutral", "negative", "mixed"], [])
    theme_options = sorted({t for lst in view["themes_list"] for t in lst})
    theme_filter = fc2.selectbox("Topic", ["Anything"] + theme_options)
    search = fc3.text_input("Search")

    feed = view.copy()
    if sent_filter:
        feed = feed[feed["sentiment"].isin(sent_filter)]
    if theme_filter != "Anything":
        feed = feed[feed["themes_list"].apply(lambda l: theme_filter in l)]
    if search:
        feed = feed[feed["text"].str.contains(search, case=False, na=False)]

    feed = feed.sort_values("created_at", ascending=False, na_position="last")
    for _, r in feed.head(150).iterrows():
        dot = SENTIMENT_COLORS.get(r["sentiment"], "#9ca3af")
        mock = " · mock" if r["is_mock"] else ""
        stars = f" · {int(r['rating'])}★" if pd.notna(r["rating"]) else ""
        st.markdown(f"<span style='color:{dot};font-weight:600'>●</span> **{r['source_label']}**{mock}{stars}",
                    unsafe_allow_html=True)
        st.write(r["text"][:600] + ("…" if len(str(r["text"])) > 600 else ""))
        tags = " ".join(f"`{t}`" for t in r["themes_list"])
        if pd.notna(r["url"]) and r["url"]:
            tags += f" · [open]({r['url']})"
        if tags.strip():
            st.caption(tags)
        st.divider()
