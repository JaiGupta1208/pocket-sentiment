"""Labeled MOCK data for sources that can't be pulled live in this build:

  - trustpilot : real reviews exist (heypocket.com, ~925 of them) but are behind an
                 AWS WAF that blocks datacenter fetches and the WebFetch/browser tools.
                 In production this uses the Trustpilot Business API (paid seat) or an
                 authenticated session scrape.
  - x          : X/Twitter search API is now $200+/mo with no free tier.
  - facebook   : Meta locked public comment access; Graph API only serves Pages you own.
  - instagram  : same Meta restriction.
  - tiktok     : no official public comment API; unofficial scrapers are fragile/ToS-grey.

Every row here is written with is_mock=1 so the dashboard can badge it "MOCK — design
only" and exclude it from headline numbers. Content is hand-written to mirror the themes
that genuinely surfaced in web-search summaries of these platforms, so the demo is
realistic without pretending to be real data.
"""
import sys, os, random, datetime
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import store

random.seed(7)

# (text, rating-or-None, leaning) — leaning is only a hint for realism, the classifier re-derives it
TRUSTPILOT = [
    ("Transcription is scarily accurate, even in meetings with three people talking over each other. Total game changer for my workflow.", 5),
    ("Battery easily lasts a full day of back-to-back calls. Genuinely impressed.", 5),
    ("Summaries sometimes invent who said what — it attributed my colleague's decision to me in the notes. Careful before you forward them.", 2),
    ("Ordered six weeks ago, still 'processing'. Support keeps sending the same copy-paste reply about shipping delays.", 1),
    ("Arrived with a scratched casing and the magnet barely holds it to my iPhone. Asked for a replacement, no response in 5 days.", 2),
    ("For neurodivergent folks this is life-changing. I stop losing thoughts mid-sentence. Cannot recommend enough.", 5),
    ("Recording quality in a noisy cafe was too muddy to be useful. Fine in a quiet room only.", 2),
    ("Customer service was FANTASTIC — real human, fixed my color-swap order same day.", 5),
    ("The magnet strength is a real concern, it fell off in my bag twice and I nearly lost it.", 3),
    ("Does exactly what it promises. Interviews, lectures, standups — all captured and summarized cleanly.", 5),
    ("Device turned itself off mid-meeting twice this week. Missing chunks of transcripts is a dealbreaker for client work.", 2),
    ("Pricey for what it is, but the time it saves me on meeting notes pays for itself.", 4),
]

X = [
    ("this tiny pocket ai recorder is wild, summarized my whole standup before i even sat down", None),
    ("$20/mo for pocket pro is steep when the free tier already does 90% of what i need tbh", None),
    ("ordered a @heypocket three weeks ago and it's still not here. anyone else stuck in shipping limbo?", None),
    ("the pocket transcription accuracy genuinely beats otter for me, especially with accents", None),
    ("not sure how i feel about a screenless recorder always listening tbh, privacy people are gonna have thoughts", None),
    ("magnet on the pocket is too weak, mine slid off my phone on the subway. heart attack.", None),
]

FACEBOOK = [
    ("Just got my Pocket in the mail, setup took literally 2 minutes. Blown away by the note quality.", None),
    ("Been waiting a month for mine, comments here suggest I'm not alone. Getting nervous about the order.", None),
    ("Does this work for phone calls or just in-person? The ad wasn't clear.", None),
    ("Love mine but wish the app had better search across old recordings.", None),
]

INSTAGRAM = [
    ("obsessed with this 😍 finally something that isn't another app on my phone", None),
    ("is it just a fancy voice memo? genuinely asking before i drop the money", None),
    ("the aesthetic is clean but $ for the pro tier is a lot for students", None),
    ("mine came in the wrong color and support hasn't replied 😤", None),
]

TIKTOK = [
    ("POV: you never take meeting notes again. this little pocket thing is unreal", None),
    ("ok but the battery life claims are actually true, i tested it all day", None),
    ("returned mine, the summaries kept making stuff up about my lectures", None),
    ("privacy tok is gonna hate this but it changed how i study fr", None),
]

BATCH = {"trustpilot": TRUSTPILOT, "x": X, "facebook": FACEBOOK, "instagram": INSTAGRAM, "tiktok": TIKTOK}


def fetch():
    rows = []
    base = datetime.datetime(2026, 6, 1)
    for source, items in BATCH.items():
        for i, item in enumerate(items):
            text, rating = item
            dt = base + datetime.timedelta(days=random.randint(0, 39), hours=random.randint(0, 23))
            rows.append({
                "source": source,
                "native_id": f"mock-{source}-{i}",
                "kind": "review" if source == "trustpilot" else "comment",
                "author": f"mock_user_{i}",
                "text": text,
                "rating": rating,
                "created_at": dt.isoformat(),
                "url": None,
                "lang": "en",
                "is_mock": 1,
            })
    return rows


if __name__ == "__main__":
    conn = store.connect()
    rows = fetch()
    n = store.upsert(conn, rows)
    print(f"mock_sources: {len(rows)} labeled-mock rows, inserted {n} new "
          f"(trustpilot/x/facebook/instagram/tiktok)")
