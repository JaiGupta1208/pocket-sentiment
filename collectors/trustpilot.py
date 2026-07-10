"""Trustpilot reviews for heypocket.com, parsed from the embedded __NEXT_DATA__ JSON
on the public review pages. No key required."""
import requests
import json
import time
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import store

BASE = "https://www.trustpilot.com/review/heypocket.com"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"}


def fetch(max_pages=40):
    rows = []
    for page in range(1, max_pages + 1):
        url = BASE if page == 1 else f"{BASE}?page={page}"
        resp = requests.get(url, headers=HEADERS, timeout=20)
        if resp.status_code != 200:
            break
        marker = '<script id="__NEXT_DATA__" type="application/json">'
        i = resp.text.find(marker)
        if i == -1:
            break
        j = resp.text.find("</script>", i)
        data = json.loads(resp.text[i + len(marker):j])
        reviews = data["props"]["pageProps"].get("reviews", [])
        if not reviews:
            break
        for r in reviews:
            rows.append({
                "source": "trustpilot",
                "native_id": r["id"],
                "kind": "review",
                "author": (r.get("consumer") or {}).get("displayName"),
                "text": ((r.get("title") or "") + ". " + (r.get("text") or "")).strip(". "),
                "rating": float(r["rating"]),
                "created_at": (r.get("dates") or {}).get("publishedDate"),
                "url": f"https://www.trustpilot.com/reviews/{r['id']}",
                "lang": r.get("language"),
            })
        time.sleep(1.5)
    return rows


if __name__ == "__main__":
    conn = store.connect()
    rows = fetch()
    n = store.upsert(conn, rows)
    print(f"trustpilot: fetched {len(rows)}, inserted {n} new")
