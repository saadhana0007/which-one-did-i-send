"""OPTIONAL: import `in:sent has:attachment` from Gmail as shares.

Needs credentials.json (OAuth desktop client, gmail.readonly). Without it, prints
setup steps and exits cleanly. Usage: python gmail_import.py [--max 50]
"""
import argparse
import base64
import os
import sys
import tempfile
from email.utils import parsedate_to_datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent
CREDS, TOKEN = BASE / "credentials.json", BASE / "token.json"
SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]

SETUP = """credentials.json not found - Gmail import is optional; the app works without it.
To enable it:
  1. Go to https://console.cloud.google.com/ and create/select a project.
  2. Enable the Gmail API (APIs & Services > Library).
  3. Configure the OAuth consent screen (External, add yourself as a test user).
  4. Credentials > Create credentials > OAuth client ID > Desktop app.
  5. Download the JSON, save it as credentials.json next to this script.
  6. Run: python gmail_import.py
Only the gmail.readonly scope is requested; attachments are hashed and discarded."""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, default=50, help="max messages to scan")
    args = ap.parse_args()
    if not CREDS.exists():
        print(SETUP)
        return 0

    from googleapiclient.discovery import build
    import db
    import engine
    import google_auth

    creds = google_auth.get_credentials(google_auth.READ_SCOPES)
    svc = build("gmail", "v1", credentials=creds)
    db.init_db()

    ids, page = [], None
    while len(ids) < args.max:
        r = svc.users().messages().list(userId="me", q="in:sent has:attachment", pageToken=page,
                                        maxResults=min(100, args.max - len(ids))).execute()
        ids += [m["id"] for m in r.get("messages", [])]
        page = r.get("nextPageToken")
        if not page:
            break

    added = 0
    for mid in ids:
        msg = svc.users().messages().get(userId="me", id=mid, format="full").execute()
        hdr = {h["name"].lower(): h["value"] for h in msg["payload"].get("headers", [])}
        to = hdr.get("to", "unknown")
        try:
            sent = parsedate_to_datetime(hdr["date"]).astimezone().replace(tzinfo=None, microsecond=0).isoformat()
        except Exception:
            sent = engine.now_iso()
        stack = [msg["payload"]]
        while stack:
            part = stack.pop()
            stack.extend(part.get("parts", []))
            aid, name = part.get("body", {}).get("attachmentId"), part.get("filename")
            if not (aid and name):
                continue
            data = svc.users().messages().attachments().get(userId="me", messageId=mid, id=aid).execute()["data"]
            with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(name)[1]) as tmp:
                tmp.write(base64.urlsafe_b64decode(data))
            try:
                r = engine.register_file(tmp.name, filename=name, modified_at=sent, stored_path=f"(gmail) {name}")
            finally:
                os.unlink(tmp.name)
            with db.connect() as con:
                dup = con.execute("SELECT 1 FROM shares WHERE sha256=? AND recipient=? AND sent_at=?",
                                  (r["sha256"], to, sent)).fetchone()
                if not dup:
                    con.execute("INSERT INTO shares(sha256, platform, recipient, sent_at, note) VALUES (?,?,?,?,?)",
                                (r["sha256"], "Gmail", to, sent, f"imported: {hdr.get('subject', '')[:80]}"))
                    added += 1
    print(f"Scanned {len(ids)} messages, recorded {added} new shares.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
