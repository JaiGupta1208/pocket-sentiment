"""Single SQLite store for all collected mentions. Common schema across sources."""
import sqlite3
import hashlib
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "data", "mentions.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS mentions (
    id TEXT PRIMARY KEY,            -- sha1(source + native_id)
    source TEXT NOT NULL,           -- appstore | play | reddit | youtube | trustpilot | x | facebook | instagram | tiktok
    native_id TEXT NOT NULL,        -- platform's own id for the item
    kind TEXT NOT NULL,             -- review | post | comment
    author TEXT,
    text TEXT NOT NULL,
    rating REAL,                    -- 1-5 where the platform has ratings, else NULL
    created_at TEXT,                -- ISO 8601
    url TEXT,
    lang TEXT,
    is_mock INTEGER DEFAULT 0,      -- 1 = mocked data, labeled on the dashboard
    collected_at TEXT DEFAULT (datetime('now')),
    -- filled by the classifier:
    sentiment TEXT,                 -- positive | negative | neutral | mixed
    themes TEXT,                    -- JSON array of theme tags
    confidence REAL,
    classified_at TEXT,
    relevant INTEGER                -- 1 = about this Pocket, 0 = off-topic (see relevance.py); NULL = unjudged
);
CREATE INDEX IF NOT EXISTS idx_source ON mentions(source);
CREATE INDEX IF NOT EXISTS idx_sentiment ON mentions(sentiment);
"""


def connect():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA)
    return conn


def make_id(source: str, native_id: str) -> str:
    return hashlib.sha1(f"{source}:{native_id}".encode()).hexdigest()


def upsert(conn, rows):
    """rows: list of dicts with source, native_id, kind, text and optional fields.
    Inserts new rows, skips ones already present. Returns count inserted."""
    inserted = 0
    for r in rows:
        rid = make_id(r["source"], str(r["native_id"]))
        cur = conn.execute(
            """INSERT OR IGNORE INTO mentions
               (id, source, native_id, kind, author, text, rating, created_at, url, lang, is_mock)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (rid, r["source"], str(r["native_id"]), r["kind"], r.get("author"),
             r["text"], r.get("rating"), r.get("created_at"), r.get("url"),
             r.get("lang"), int(r.get("is_mock", 0))),
        )
        inserted += cur.rowcount
    conn.commit()
    return inserted
