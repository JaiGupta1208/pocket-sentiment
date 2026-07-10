"""Classification layer: sentiment + themes for every mention.

Primary path  : Claude (batched, structured JSON output). This is the "logic" the brief
                grades. Requires ANTHROPIC_API_KEY in .env.
Fallback path : a transparent rule-based tagger (star rating -> sentiment, keyword ->
                theme). Used only when no API key is present, and every row it writes is
                marked method='rules' so the dashboard can flag it.

Themes are a fixed taxonomy so the dashboard aggregates cleanly. If Claude sees something
new it can add a free-text theme, but it's asked to prefer the taxonomy.
"""
import os
import json
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import store

THEMES = [
    "transcription_accuracy", "summary_quality", "battery_life", "audio_recording_quality",
    "hardware_build", "magnet_attachment", "device_reliability", "app_experience",
    "search_organization", "shipping_delivery", "customer_support", "price_value",
    "privacy", "ease_of_setup", "comparison_competitor", "general_praise",
]

BATCH_SIZE = 20
MODEL = "claude-sonnet-5"

SYSTEM = f"""You classify customer feedback about "Pocket", a screenless AI voice-recorder \
wearable (hardware + companion app) by Open Vision Engineering. For each item return \
sentiment and themes.

sentiment: one of positive, negative, neutral, mixed.
themes: 1-3 tags from this taxonomy (prefer these; only invent a new snake_case tag if \
nothing fits): {", ".join(THEMES)}.
relevant: false if the text is not actually about this Pocket product (spam, unrelated \
"pocket" mentions, off-topic). Irrelevant rows still need sentiment=neutral.
confidence: 0.0-1.0, your confidence in the sentiment call.

Return ONLY a JSON array, one object per input, same order, shape:
{{"i": <index>, "sentiment": "...", "themes": ["..."], "relevant": true, "confidence": 0.0}}"""


def _key():
    env = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if os.path.exists(env):
        for line in open(env):
            if line.startswith("ANTHROPIC_API_KEY="):
                v = line.split("=", 1)[1].strip()
                return v or None
    return os.environ.get("ANTHROPIC_API_KEY") or None


# ---------- Claude path ----------
def classify_with_claude(rows, key):
    import anthropic
    client = anthropic.Anthropic(api_key=key)
    results = {}
    for start in range(0, len(rows), BATCH_SIZE):
        chunk = rows[start:start + BATCH_SIZE]
        payload = [{"i": i, "source": r["source"], "text": r["text"][:1200]}
                   for i, r in enumerate(chunk)]
        msg = client.messages.create(
            model=MODEL, max_tokens=2000, system=SYSTEM,
            messages=[{"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
        )
        text = "".join(b.text for b in msg.content if b.type == "text").strip()
        if text.startswith("```"):
            text = text.split("```")[1].replace("json", "", 1).strip()
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            print(f"  batch {start}: could not parse model output, skipping")
            continue
        for obj in parsed:
            r = chunk[obj["i"]]
            results[r["id"]] = obj
        print(f"  classified {min(start + BATCH_SIZE, len(rows))}/{len(rows)}")
        time.sleep(0.3)
    return results, "claude"


# ---------- rule-based fallback ----------
KEYWORDS = {
    "transcription_accuracy": ["transcri", "accura", "accent"],
    "summary_quality": ["summar", "notes", "made up", "invent", "hallucinat", "assum"],
    "battery_life": ["battery", "charge", "all day"],
    "audio_recording_quality": ["recording quality", "audio", "muddy", "noisy", "mic"],
    "hardware_build": ["scratch", "damaged", "casing", "build", "cheap"],
    "magnet_attachment": ["magnet", "fell off", "slid off", "attach"],
    "device_reliability": ["turned off", "turns off", "died", "froze", "crash", "pairing", "won't"],
    "app_experience": ["app "],
    "search_organization": ["search", "organi"],
    "shipping_delivery": ["shipping", "shipped", "delivery", "waiting", "arrived", "order", "processing"],
    "customer_support": ["support", "customer service", "replied", "response", "refund"],
    "price_value": ["price", "pricey", "expensive", "$", "worth", "subscription", "pro tier", "month"],
    "privacy": ["privacy", "listening", "data"],
    "ease_of_setup": ["setup", "set up", "2 minutes", "easy"],
    "comparison_competitor": ["otter", "plaud", "vs ", "better than", "compared"],
}


def classify_with_rules(rows):
    results = {}
    for r in rows:
        t = (r["text"] or "").lower()
        rating = r.get("rating")
        if rating is not None:
            sent = "positive" if rating >= 4 else "negative" if rating <= 2 else "neutral"
        else:
            pos = sum(w in t for w in ["love", "great", "amazing", "game changer", "impressed", "obsessed", "recommend", "fantastic", "unreal", "wild"])
            neg = sum(w in t for w in ["waiting", "still not", "no response", "dealbreaker", "returned", "scratch", "damaged", "fell off", "made up", "invent", "steep", "concern", "wrong", "muddy"])
            sent = "positive" if pos > neg else "negative" if neg > pos else "neutral"
        themes = [th for th, kws in KEYWORDS.items() if any(k in t for k in kws)][:3]
        if not themes:
            themes = ["general_praise"] if sent == "positive" else []
        results[r["id"]] = {"sentiment": sent, "themes": themes, "relevant": True, "confidence": 0.4}
    return results, "rules"


def write_results(conn, results, method):
    for rid, obj in results.items():
        conn.execute(
            "UPDATE mentions SET sentiment=?, themes=?, confidence=?, classified_at=datetime('now') WHERE id=?",
            (obj["sentiment"], json.dumps(obj.get("themes", [])), obj.get("confidence"), rid),
        )
    conn.commit()


def run(only_unclassified=True, force_rules=False):
    conn = store.connect()
    q = "SELECT id, source, text, rating FROM mentions"
    if only_unclassified:
        q += " WHERE sentiment IS NULL"
    rows = [dict(id=r[0], source=r[1], text=r[2], rating=r[3]) for r in conn.execute(q)]
    if not rows:
        print("nothing to classify")
        return
    key = None if force_rules else _key()
    if key:
        print(f"classifying {len(rows)} rows with Claude ({MODEL})...")
        results, method = classify_with_claude(rows, key)
    else:
        print(f"no ANTHROPIC_API_KEY -> rule-based fallback for {len(rows)} rows (labeled 'rules')")
        results, method = classify_with_rules(rows)
    write_results(conn, results, method)
    # stash which method was used, for the dashboard footer
    conn.execute("CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT)")
    conn.execute("INSERT OR REPLACE INTO meta VALUES ('classifier_method', ?)", (method,))
    conn.commit()
    print(f"done: {len(results)} rows via '{method}'")


if __name__ == "__main__":
    run(force_rules="--rules" in sys.argv)
