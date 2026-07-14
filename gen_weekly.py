"""Weekly pulse: per-week sentiment scores + AI-written summaries.

Aggregates relevant real mentions by week, computes a net sentiment score
(% positive minus % negative), and asks the AI model for a 2-3 sentence plain-English
summary of what dominated each week. Results land in the `weekly_summaries` table so the
dashboard reads them instantly — no API calls at view time.

Run after collection/classification: python gen_weekly.py
Re-running only fills weeks that are missing or whose mention count changed.
"""
import os
import sys
import json
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import store
from classify import _key

MODEL = "claude-sonnet-5"
MIN_WEEK_N = 5          # skip weeks with fewer mentions than this
MAX_TEXTS_PER_WEEK = 25  # sample cap sent to the model per week

TABLE = """
CREATE TABLE IF NOT EXISTS weekly_summaries (
    week_start TEXT PRIMARY KEY,   -- ISO date (Monday)
    n INTEGER,
    pos INTEGER,
    neg INTEGER,
    net REAL,                      -- %positive - %negative
    summary TEXT,
    generated_at TEXT DEFAULT (datetime('now'))
);
"""

SYSTEM = """You write a short weekly digest of customer chatter about "Pocket", a screenless \
AI voice-recorder wearable. You get one week of real comments (reviews, Reddit, YouTube).

Write 2-3 plain sentences: what dominated the conversation that week, any notable complaints \
or praise, and anything new or shifting. Sound like a sharp colleague summarizing for the team \
— specific, concrete, no hype, no bullet points, no preamble. Never invent facts not present \
in the comments."""


def week_rows(conn):
    """Weekly aggregates for relevant real mentions since Dec 2025."""
    q = """
    SELECT date(created_at, 'weekday 0', '-6 days') wk,
           count(*) n,
           sum(sentiment='positive') pos,
           sum(sentiment='negative') neg
    FROM mentions
    WHERE is_mock=0 AND relevant=1 AND created_at >= '2025-12-01'
    GROUP BY wk ORDER BY wk
    """
    return [dict(week=r[0], n=r[1], pos=r[2], neg=r[3]) for r in conn.execute(q)]


def sample_texts(conn, week_start):
    """A readable sample for the model: negatives first, then the rest, capped."""
    q = """
    SELECT text, sentiment FROM mentions
    WHERE is_mock=0 AND relevant=1
      AND date(created_at, 'weekday 0', '-6 days') = ?
    ORDER BY (sentiment='negative') DESC, confidence DESC
    LIMIT ?
    """
    return [(t[:400], s) for t, s in conn.execute(q, (week_start, MAX_TEXTS_PER_WEEK))]


def summarize(client, week, texts):
    payload = "\n".join(f"[{s}] {t}" for t, s in texts)
    msg = client.messages.create(
        model=MODEL, max_tokens=1000, system=SYSTEM,
        messages=[{"role": "user", "content": f"Week of {week}:\n{payload}"}],
    )
    return "".join(b.text for b in msg.content if b.type == "text").strip()


def run(force=False):
    conn = store.connect()
    conn.executescript(TABLE)
    key = _key()
    weeks = [w for w in week_rows(conn) if w["n"] >= MIN_WEEK_N]
    existing = {r[0]: r[1] for r in conn.execute("SELECT week_start, n FROM weekly_summaries")}

    client = None
    todo = [w for w in weeks if force or w["week"] not in existing or existing[w["week"]] != w["n"]]
    print(f"{len(weeks)} weeks total, {len(todo)} to (re)generate")
    if todo and key:
        import anthropic
        client = anthropic.Anthropic(api_key=key)

    for w in weeks:
        net = round((w["pos"] - w["neg"]) / w["n"] * 100, 1)
        summary = None
        if w in todo and client:
            try:
                summary = summarize(client, w["week"], sample_texts(conn, w["week"]))
                print(f"  {w['week']}: n={w['n']}, net={net:+.0f} — summarized")
                time.sleep(0.3)
            except Exception as e:
                print(f"  {w['week']}: summary failed ({e}); keeping stats only")
        if summary is not None:
            conn.execute("INSERT OR REPLACE INTO weekly_summaries VALUES (?,?,?,?,?,?,datetime('now'))",
                         (w["week"], w["n"], w["pos"], w["neg"], net, summary))
        else:
            # keep existing summary if present; update stats
            old = conn.execute("SELECT summary FROM weekly_summaries WHERE week_start=?", (w["week"],)).fetchone()
            conn.execute("INSERT OR REPLACE INTO weekly_summaries VALUES (?,?,?,?,?,?,datetime('now'))",
                         (w["week"], w["n"], w["pos"], w["neg"], net, old[0] if old else None))
    conn.commit()
    print("weekly_summaries up to date:",
          conn.execute("SELECT count(*) FROM weekly_summaries").fetchone()[0], "weeks")


if __name__ == "__main__":
    run(force="--force" in sys.argv)
