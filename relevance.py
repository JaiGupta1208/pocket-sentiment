"""Relevance pass: flag mentions that aren't actually about *this* Pocket.

"Pocket" is an ambiguous word (Mozilla/Firefox Pocket, Pocket Casts, Pokemon TCG Pocket,
pocket knives, "out of pocket"...). Collection matches at the thread/video level, so some
real Reddit/YouTube text is on a different topic. This pass asks Claude, per mention,
whether it's actually about the Open Vision Engineering Pocket voice-recorder wearable,
and stores the answer in a `relevant` column (1/0).

App Store + Google Play reviews and the labelled mocks are relevant by construction, so we
only spend the model on Reddit + YouTube.
"""
import os
import sys
import json
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import store
from classify import _key

MODEL = "claude-sonnet-5"
BATCH = 20
JUDGE_SOURCES = ("reddit", "youtube")

SYSTEM = """You decide whether each snippet is actually about "Pocket" — a screenless AI \
voice-recorder wearable made by Open Vision Engineering (heypocket.com). It's a small \
device you clip on or wear that records conversations and produces AI transcripts and \
summaries via a companion app.

"Pocket" is an ambiguous word. Mark relevant=false when a snippet is clearly about \
something else, for example:
- Mozilla / Firefox Pocket (the save-articles / read-it-later app)
- Pocket Casts, Pokemon TCG Pocket, pocket knives, pants pockets, "out of pocket", pocket money
- generic AI, tech, or workflow talk with no connection to this recorder
- spam or pure off-topic replies

Mark relevant=true when it plausibly refers to this recorder/wearable or a discussion of \
it: reviews, shipping, battery, transcription, summaries, the app, the company/founder, \
"my device", "Founder's Edition", the Kickstarter, comparisons to Plaud / Limitless / \
Otter / Bee, etc. — even if it doesn't say "Pocket" explicitly, as long as it reads like \
part of a thread about the product.

When genuinely unsure, prefer relevant=true — do not over-filter.

Return ONLY a JSON array, one object per input, same order and index:
[{"i": 0, "relevant": true}, {"i": 1, "relevant": false}]"""


def judge_with_claude(rows, key):
    import anthropic
    client = anthropic.Anthropic(api_key=key)
    out = {}
    for start in range(0, len(rows), BATCH):
        chunk = rows[start:start + BATCH]
        payload = [{"i": i, "text": r["text"][:1000]} for i, r in enumerate(chunk)]
        msg = client.messages.create(
            model=MODEL, max_tokens=1500, system=SYSTEM,
            messages=[{"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
        )
        text = "".join(b.text for b in msg.content if b.type == "text").strip()
        if text.startswith("```"):
            text = text.split("```")[1].replace("json", "", 1).strip()
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            print(f"  batch {start}: parse failed, marking chunk relevant (safe default)")
            for r in chunk:
                out[r["id"]] = 1
            continue
        for obj in parsed:
            r = chunk[obj["i"]]
            out[r["id"]] = 1 if obj.get("relevant", True) else 0
        print(f"  judged {min(start + BATCH, len(rows))}/{len(rows)}")
        time.sleep(0.3)
    return out


def run(only_new=False):
    """only_new=True judges just the rows without a relevance flag yet (cheap refresh)."""
    conn = store.connect()
    cols = [c[1] for c in conn.execute("PRAGMA table_info(mentions)")]
    if "relevant" not in cols:
        conn.execute("ALTER TABLE mentions ADD COLUMN relevant INTEGER")
        conn.commit()

    # Everything that isn't Reddit/YouTube is relevant by construction.
    conn.execute(
        "UPDATE mentions SET relevant=1 WHERE source NOT IN (?, ?)", JUDGE_SOURCES)
    conn.commit()

    q = "SELECT id, text FROM mentions WHERE source IN (?, ?)"
    if only_new:
        q += " AND relevant IS NULL"
    rows = [dict(id=r[0], text=r[1]) for r in conn.execute(q, JUDGE_SOURCES)]
    if not rows:
        print("relevance: nothing new to judge")
        return
    key = _key()
    if not key:
        print("no ANTHROPIC_API_KEY — cannot run relevance pass")
        return
    print(f"judging relevance for {len(rows)} Reddit/YouTube rows with {MODEL}...")
    results = judge_with_claude(rows, key)
    for rid, rel in results.items():
        conn.execute("UPDATE mentions SET relevant=? WHERE id=?", (rel, rid))
    conn.commit()

    tot = conn.execute("SELECT count(*) FROM mentions").fetchone()[0]
    irr = conn.execute("SELECT count(*) FROM mentions WHERE relevant=0").fetchone()[0]
    print(f"done: {irr} of {tot} flagged off-topic")
    for src, n in conn.execute(
            "SELECT source, count(*) FROM mentions WHERE relevant=0 GROUP BY source"):
        print(f"  off-topic {src}: {n}")


if __name__ == "__main__":
    run()
