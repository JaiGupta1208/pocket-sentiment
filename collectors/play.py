"""Google Play reviews via google-play-scraper. No key required."""
from google_play_scraper import reviews, Sort
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import store

PACKAGE = "com.heypocket.app"


def fetch(max_reviews=1000):
    rows, token = [], None
    while len(rows) < max_reviews:
        batch, token = reviews(PACKAGE, lang="en", country="us",
                               sort=Sort.NEWEST, count=200, continuation_token=token)
        for r in batch:
            rows.append({
                "source": "play",
                "native_id": r["reviewId"],
                "kind": "review",
                "author": r["userName"],
                "text": r["content"] or "",
                "rating": float(r["score"]),
                "created_at": r["at"].isoformat() if r["at"] else None,
                "url": f"https://play.google.com/store/apps/details?id={PACKAGE}",
                "lang": "en",
            })
        if token is None or not batch:
            break
    return [r for r in rows if r["text"].strip()]


if __name__ == "__main__":
    conn = store.connect()
    rows = fetch()
    n = store.upsert(conn, rows)
    print(f"play: fetched {len(rows)}, inserted {n} new")
