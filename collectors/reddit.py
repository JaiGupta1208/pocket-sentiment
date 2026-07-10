"""Reddit posts + comments.

Reddit blocks datacenter IPs on the public .json endpoints (HTTP 403), and getting
a script-app OAuth credential was not possible for this account. The working path used
for the real data in this project was a *browser-session* pull: the same fetch logic
below, run inside a logged-in Chrome tab (residential IP), with results saved to
Downloads/pocket_reddit.json and loaded via load_reddit_download().

This module keeps both paths:
  - fetch_via_json(): the direct approach (works from a residential IP / with a proxy)
  - load_reddit_download(path): load the browser-exported JSON into the store

The browser JS used is documented in README.md under "Reddit".
"""
import requests
import time
import json
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import store

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"}
QUERIES = ["heypocket", "pocket ai wearable", "pocket ai voice recorder",
           "open vision engineering pocket", "hey pocket recorder"]


def relevant(text):
    return "pocket" in (text or "").lower()


def fetch_via_json():
    """Direct .json pull. Returns [] with a warning if Reddit blocks the IP."""
    rows, seen = [], set()
    for q in QUERIES:
        try:
            r = requests.get("https://www.reddit.com/search.json",
                             params={"q": q, "limit": 100, "sort": "new", "t": "all"},
                             headers=HEADERS, timeout=20)
            r.raise_for_status()
        except Exception as e:
            print(f"  search blocked for {q!r}: {e} -- use the browser path (see README)")
            continue
        for child in r.json().get("data", {}).get("children", []):
            p = child["data"]
            if p["id"] in seen:
                continue
            seen.add(p["id"])
            text = (p.get("title", "") + "\n" + p.get("selftext", "")).strip()
            if not relevant(text):
                continue
            rows.append({"source": "reddit", "native_id": p["id"], "kind": "post",
                         "author": p.get("author"), "text": text[:4000],
                         "created_at": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(p["created_utc"])),
                         "url": "https://www.reddit.com" + p["permalink"], "lang": "en"})
            time.sleep(1.1)
    return rows


def load_reddit_download(path):
    rows = json.load(open(path, encoding="utf-8"))
    for r in rows:
        r.setdefault("lang", "en")
    return rows


if __name__ == "__main__":
    conn = store.connect()
    download = os.path.join(os.path.expanduser("~"), "Downloads", "pocket_reddit.json")
    if os.path.exists(download):
        rows = load_reddit_download(download)
        print(f"reddit: loading {len(rows)} rows from browser export {download}")
    else:
        rows = fetch_via_json()
    n = store.upsert(conn, rows)
    print(f"reddit: inserted {n} new")
