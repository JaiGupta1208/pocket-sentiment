"""YouTube: find videos about Pocket, pull their comments. Uses YouTube Data API v3."""
import requests
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import store

API = "https://www.googleapis.com/youtube/v3"
QUERIES = ["heypocket review", "pocket ai voice recorder", "pocket ai wearable review"]


def api_key():
    env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
    for line in open(env_path):
        if line.startswith("YOUTUBE_API_KEY="):
            return line.split("=", 1)[1].strip()
    raise RuntimeError("YOUTUBE_API_KEY not found in .env")


def fetch():
    key = api_key()
    video_ids, video_titles = [], {}
    for q in QUERIES:
        resp = requests.get(f"{API}/search", params={
            "part": "snippet", "q": q, "type": "video", "maxResults": 15,
            "relevanceLanguage": "en", "key": key}, timeout=20).json()
        for item in resp.get("items", []):
            vid = item["id"]["videoId"]
            title = item["snippet"]["title"].lower()
            # keep only videos plausibly about this product
            if "pocket" in title:
                video_ids.append(vid)
                video_titles[vid] = item["snippet"]["title"]
    video_ids = list(dict.fromkeys(video_ids))

    rows = []
    for vid in video_ids:
        page_token = None
        while True:
            params = {"part": "snippet", "videoId": vid, "maxResults": 100,
                      "textFormat": "plainText", "order": "relevance", "key": key}
            if page_token:
                params["pageToken"] = page_token
            resp = requests.get(f"{API}/commentThreads", params=params, timeout=20).json()
            if "error" in resp:
                break  # comments disabled etc.
            for item in resp.get("items", []):
                s = item["snippet"]["topLevelComment"]["snippet"]
                rows.append({
                    "source": "youtube",
                    "native_id": item["id"],
                    "kind": "comment",
                    "author": s.get("authorDisplayName"),
                    "text": s.get("textDisplay", "")[:4000],
                    "created_at": s.get("publishedAt"),
                    "url": f"https://www.youtube.com/watch?v={vid}&lc={item['id']}",
                    "lang": "en",
                })
            page_token = resp.get("nextPageToken")
            if not page_token or len(rows) > 3000:
                break
    return rows, video_titles


if __name__ == "__main__":
    conn = store.connect()
    rows, titles = fetch()
    n = store.upsert(conn, rows)
    print(f"youtube: {len(titles)} videos, fetched {len(rows)} comments, inserted {n} new")
    for vid, t in titles.items():
        print(f"  {vid}: {t}".encode("ascii", "replace").decode())
