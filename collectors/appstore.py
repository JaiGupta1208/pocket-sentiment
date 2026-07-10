"""Apple App Store reviews, parsed from the review objects Apple server-renders
into the app page HTML ({"$kind":"Review",...}). The old RSS feed is dead and the
amp-api token is no longer embedded, so this is the most reliable keyless path.
Coverage: the reviews Apple surfaces per storefront (not the full history)."""
import requests
import json
import time
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import store

APP_ID = "6746845735"  # Pocket - AI Personal Assistant
SLUG = "pocket-ai-personal-assistant"
COUNTRIES = ["us", "gb", "ca", "au", "in", "de", "nl", "sg"]
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"}

decoder = json.JSONDecoder()


def extract_reviews(html):
    out, i = [], 0
    needle = '{"$kind":"Review","id":'
    while True:
        i = html.find(needle, i)
        if i == -1:
            break
        try:
            obj, _ = decoder.raw_decode(html[i:i + 20000])
            out.append(obj)
        except json.JSONDecodeError:
            pass
        i += len(needle)
    return out


def fetch():
    rows = []
    for country in COUNTRIES:
        url = f"https://apps.apple.com/{country}/app/{SLUG}/id{APP_ID}"
        try:
            resp = requests.get(url, headers=HEADERS, timeout=20)
        except requests.RequestException:
            continue
        if resp.status_code != 200:
            continue
        for r in extract_reviews(resp.text):
            text = ((r.get("title") or "") + ". " + (r.get("contents") or "")).strip(". ")
            if not text:
                continue
            rows.append({
                "source": "appstore",
                "native_id": r["id"],
                "kind": "review",
                "author": r.get("reviewerName"),
                "text": text[:4000],
                "rating": float(r["rating"]) if r.get("rating") else None,
                "created_at": r.get("date"),
                "url": url,
                "lang": country,
            })
        time.sleep(1)
    return rows


if __name__ == "__main__":
    conn = store.connect()
    rows = fetch()
    n = store.upsert(conn, rows)
    print(f"appstore: fetched {len(rows)}, inserted {n} new")
