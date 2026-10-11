# Which One Did I Send?

Local-first tracker that identifies files by **content** (SHA-256 + text similarity), not filename,
and records which version went to whom, on which platform, and when. Only hashes and metadata are stored.

## Run (Windows PowerShell; Python 3.11+)

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python seed_demo.py                       # demo PDFs + shares (re-runnable)
.\.venv\Scripts\python -m uvicorn main:app --port 8000    # open http://localhost:8000
```

macOS/Linux: use `.venv/bin/python` instead. Env vars: `WATCH_DIR` (default `./watched`), `TRACKER_DB` (default `./tracker.db`).
Optional smoke test (server running): `.\.venv\Scripts\python smoke.py`

## Demo script

1. Open http://localhost:8000. Two red alerts show outdated sends.
2. Ask **"what did I send to prof"** → `assignment_final2.pdf sent to prof.kumar@ssn.edu.in via Gmail on <date>` plus a red *Newer version exists* banner.
3. Click the family: timeline shows 3 versions (dots, short hashes) and the WhatsApp/Gmail sends.
4. In `watched/`, rename `assignment_final2.pdf` to `random.pdf`. Ask again: still identified (card says the file is now named `random.pdf`), no new version appears.
5. Drop a new file into `watched/`: it appears in the list within ~3 s.
6. "Log a send": pick a file, platform, recipient, submit. The timeline and alerts update.
   Re-logging the newest version to the professor clears the alert.

## Sending from the app

- **Gmail (real send):** one-time authorisation: `python google_auth.py` (adds the `gmail.send` scope; approve in the browser).
  Then choose Platform = Gmail, a file, a recipient, and **Send via Gmail**. A confirm dialog appears; the email goes out with the
  file attached and the share is logged automatically.
- **WhatsApp (link):** WhatsApp has no API for personal accounts, so it can't carry attachments. **Upload to Drive & open WhatsApp**
  uploads the file to your Google Drive (link-shared: anyone with the link can view; confirm dialog warns), puts the link in the message,
  and shows chat links (WhatsApp Web / wa.me / desktop app). You press send, then click **I sent it - log it**.
  Needs the Drive API enabled in your Google Cloud project and `python google_auth.py` re-run (adds `drive.file`).
  **Open WhatsApp (text only)** skips the upload. Use your normal browser, not an embedded preview pane. 10-digit numbers get `91` added.
- **Drive / LMS / Other:** **Log only**.

## Files

`engine.py` hash/extract/MinHash/family · `watcher.py` folder watcher · `main.py` API + static page ·
`static/index.html` UI · `seed_demo.py` demo data · `gmail_import.py` optional import · `smoke.py` quick checks

## Optional: Gmail import (read-only history)

`python gmail_import.py` prints setup steps if `credentials.json` is missing. With it, it OAuths (`gmail.readonly`),
scans `in:sent has:attachment`, hashes attachments and records Gmail shares.

## Known limitations

- Family matching uses text only: scanned/image PDFs and images fall back to exact-hash, one family per distinct file.
- A new version joins the family of its most similar existing version (Jaccard >= 0.6 on word 3-shingles); heavily rewritten drafts start a new family.
- "Newer" means a later file modified time; copying a file can change its mtime and confuse ordering.
- Edited-in-place files register a new version, but older versions' stored paths are stale (the old bytes are gone).
- Uploads via the form use the browser's `lastModified` as the version date; Gmail imports use the email date.
- Question parsing is keyword-based (recipient, platform, filename/note words), not NLP.
- Smoke test assumes the clean demo data (run `seed_demo.py` first; it clears imported shares).
- No auth; intended for localhost only. Watcher on OneDrive/network folders can fire extra events (harmless: same hash is a no-op).
