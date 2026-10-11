"""SQLite helpers. Only hashes + metadata are stored, never file contents."""
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
ON_VERCEL = bool(os.environ.get("VERCEL"))  # serverless: only /tmp is writable (and it is ephemeral)
DB_PATH = os.environ.get("TRACKER_DB", "/tmp/tracker.db" if ON_VERCEL else str(BASE_DIR / "tracker.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS families (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    display_name TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS versions (
    sha256 TEXT PRIMARY KEY,
    family_id INTEGER NOT NULL REFERENCES families(id),
    filename TEXT NOT NULL,
    path TEXT,
    size INTEGER,
    modified_at TEXT NOT NULL,
    minhash BLOB,
    first_seen_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS shares (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sha256 TEXT NOT NULL REFERENCES versions(sha256),
    platform TEXT NOT NULL,
    recipient TEXT NOT NULL,
    sent_at TEXT NOT NULL,
    note TEXT
);
CREATE INDEX IF NOT EXISTS idx_versions_family ON versions(family_id);
CREATE INDEX IF NOT EXISTS idx_shares_sha ON shares(sha256);
"""


@contextmanager
def connect():
    """Autocommit connection (use `BEGIN IMMEDIATE` explicitly for write transactions)."""
    con = sqlite3.connect(DB_PATH, timeout=15, isolation_level=None)
    con.row_factory = sqlite3.Row
    try:
        yield con
    except Exception:
        if con.in_transaction:
            con.execute("ROLLBACK")
        raise
    finally:
        con.close()


def init_db():
    with connect() as con:
        con.executescript(SCHEMA)
