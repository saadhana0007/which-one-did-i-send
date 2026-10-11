"""FastAPI app: API + static frontend + folder watcher."""
import os
import re
import tempfile
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

import db
import engine
import watcher

STATIC = Path(__file__).resolve().parent / "static"


@asynccontextmanager
async def lifespan(app):
    db.init_db()
    if db.ON_VERCEL:  # serverless demo: no folder watcher / persistent disk, so seed the synthetic demo data
        with db.connect() as con:
            empty = con.execute("SELECT COUNT(*) FROM families").fetchone()[0] == 0
        if empty:
            import seed_demo
            seed_demo.main()
        yield
        return
    obs = watcher.start()
    yield
    obs.stop()


app = FastAPI(title="Which One Did I Send?", lifespan=lifespan)


# ---------- helpers ----------
def ver(r) -> dict:
    return {"sha256": r["sha256"], "short": r["sha256"][:8], "family_id": r["family_id"],
            "filename": r["filename"], "path": r["path"], "size": r["size"],
            "modified_at": r["modified_at"], "first_seen_at": r["first_seen_at"]}


def share(r) -> dict:
    return {"id": r["id"], "sha256": r["sha256"], "short": r["sha256"][:8], "platform": r["platform"],
            "recipient": r["recipient"], "sent_at": r["sent_at"], "note": r["note"]}


def latest_version(con, fid):
    return con.execute("SELECT * FROM versions WHERE family_id=? ORDER BY modified_at DESC, first_seen_at DESC LIMIT 1",
                       (fid,)).fetchone()


def last_share(con, fid):
    return con.execute("SELECT s.* FROM shares s JOIN versions v ON v.sha256=s.sha256 WHERE v.family_id=? "
                       "ORDER BY s.sent_at DESC, s.id DESC LIMIT 1", (fid,)).fetchone()


def is_outdated(sent, latest) -> bool:
    return sent["sha256"] != latest["sha256"] and latest["modified_at"] > sent["modified_at"]


def fmt(iso: str) -> str:
    d = datetime.fromisoformat(iso)
    return f"{d.day} {d:%b}, {d.hour % 12 or 12}:{d:%M} {d:%p}"


def parse_dt(s: Optional[str]) -> str:
    if not s:
        return engine.now_iso()
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if d.tzinfo:
            d = d.astimezone().replace(tzinfo=None)
        return d.replace(microsecond=0).isoformat()
    except ValueError:
        return engine.now_iso()


# ---------- API ----------
@app.get("/api/families")
def families():
    with db.connect() as con:
        out = []
        for f in con.execute("SELECT * FROM families"):
            latest = latest_version(con, f["id"])
            ls = last_share(con, f["id"])
            sent = con.execute("SELECT * FROM versions WHERE sha256=?", (ls["sha256"],)).fetchone() if ls else None
            out.append({
                "id": f["id"], "display_name": f["display_name"],
                "version_count": con.execute("SELECT COUNT(*) FROM versions WHERE family_id=?", (f["id"],)).fetchone()[0],
                "latest_version": ver(latest),
                "last_share": share(ls) | {"filename": sent["filename"]} if ls else None,
                "outdated": bool(ls and is_outdated(sent, latest)),
            })
    out.sort(key=lambda x: x["latest_version"]["modified_at"], reverse=True)
    return out


@app.get("/api/families/{fid}/timeline")
def timeline(fid: int):
    with db.connect() as con:
        f = con.execute("SELECT * FROM families WHERE id=?", (fid,)).fetchone()
        if not f:
            raise HTTPException(404, "family not found")
        latest = latest_version(con, fid)
        vers = con.execute("SELECT * FROM versions WHERE family_id=?", (fid,)).fetchall()
        shares = con.execute("SELECT s.* FROM shares s JOIN versions v ON v.sha256=s.sha256 WHERE v.family_id=?",
                             (fid,)).fetchall()
        by_sha = {v["sha256"]: v for v in vers}
        events = [{"type": "version", "at": v["modified_at"], "is_latest": v["sha256"] == latest["sha256"], **ver(v)}
                  for v in vers]
        for s in shares:
            events.append({"type": "share", "at": s["sent_at"], "filename": by_sha[s["sha256"]]["filename"],
                           "outdated": is_outdated(by_sha[s["sha256"]], latest), **share(s)})
    events.sort(key=lambda e: (e["at"], e["type"] == "share"))  # a version precedes a same-instant share
    return {"family": {"id": f["id"], "display_name": f["display_name"]}, "events": events}


MAX_BYTES = 25 * 1024 * 1024
EMAIL_RE = re.compile(r"^[^@\s<>,;]+@[^@\s<>,;]+\.[^@\s<>,;]+$")


def ingest(data: bytes, filename: str, modified_at: Optional[str]) -> dict:
    """Register uploaded bytes as a version (via a temp file for text extraction)."""
    with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(filename)[1]) as tmp:
        tmp.write(data)
    try:
        return engine.register_file(tmp.name, filename=filename, modified_at=parse_dt(modified_at),
                                    stored_path=f"(upload) {filename}")
    finally:
        os.unlink(tmp.name)


def record_share(sha, platform, recipient, sent_at, note, new_version=False) -> dict:
    with db.connect() as con:
        v = con.execute("SELECT * FROM versions WHERE sha256=?", (sha,)).fetchone()
        if not v:
            raise HTTPException(404, "unknown sha256 (upload the file instead)")
        cur = con.execute("INSERT INTO shares(sha256, platform, recipient, sent_at, note) VALUES (?,?,?,?,?)",
                          (sha, platform.strip(), recipient.strip(), parse_dt(sent_at), note.strip()))
        s = con.execute("SELECT * FROM shares WHERE id=?", (cur.lastrowid,)).fetchone()
        latest = latest_version(con, v["family_id"])
        return {"share": share(s), "version": ver(v), "family_id": v["family_id"],
                "new_version": new_version, "outdated": is_outdated(v, latest)}


def tracked_file(sha: str):
    """Path of a tracked version that is still on disk with the exact registered bytes."""
    with db.connect() as con:
        v = con.execute("SELECT * FROM versions WHERE sha256=?", (sha,)).fetchone()
    if not v:
        raise HTTPException(404, "unknown sha256")
    p = v["path"] or ""
    if p.startswith("(") or not os.path.isfile(p):
        raise HTTPException(404, "that version is not on disk any more; pick the file again")
    if engine.hash_file(p) != sha:
        raise HTTPException(409, "the file changed since it was registered; pick the current file")
    return p, v["filename"]


@app.post("/api/shares")
async def create_share(platform: str = Form(...), recipient: str = Form(...), note: str = Form(""),
                       sha256: Optional[str] = Form(None), sent_at: Optional[str] = Form(None),
                       modified_at: Optional[str] = Form(None), file: Optional[UploadFile] = File(None)):
    """Log-only: records that a file was sent; nothing is sent by this endpoint."""
    r = None
    if file is not None and file.filename:
        r = ingest(await file.read(), file.filename, modified_at)
        sha = r["sha256"]
    elif sha256:
        sha = sha256.strip().lower()
    else:
        raise HTTPException(400, "provide a file upload or a sha256")
    return record_share(sha, platform, recipient, sent_at, note, bool(r and r["new"]))


@app.get("/api/versions")
def versions():
    """Tracked versions still on disk (pickable in the send form)."""
    with db.connect() as con:
        rows = con.execute("SELECT * FROM versions ORDER BY modified_at DESC").fetchall()
    return [ver(r) for r in rows if r["path"] and not r["path"].startswith("(") and os.path.isfile(r["path"])]


@app.get("/api/files/{sha}")
def download(sha: str):
    """Serve a tracked file (localhost helper so it can be attached in WhatsApp)."""
    path, name = tracked_file(sha.lower())
    return FileResponse(path, filename=name)


@app.get("/api/google/status")
def google_status():
    import google_auth
    return {"can_send": google_auth.has_scopes(google_auth.SEND_SCOPES),
            "can_drive": google_auth.has_scopes(google_auth.DRIVE_SCOPES)}


@app.post("/api/send/drive-link")
def drive_link(confirm: str = Form(""), sha256: Optional[str] = Form(None), modified_at: Optional[str] = Form(None),
               file: Optional[UploadFile] = File(None)):
    """Uploads the file to the user's Google Drive, link-shared ("anyone with the link can view"). Requires confirm=yes."""
    import google_auth
    import senders
    if confirm != "yes":
        raise HTTPException(400, "uploading must be confirmed (confirm=yes)")
    if file is not None and file.filename:
        data, filename = file.file.read(), file.filename
        if len(data) > MAX_BYTES * 4:
            raise HTTPException(413, "file is larger than 100 MB")
        sha = ingest(data, filename, modified_at)["sha256"]
    elif sha256:
        sha = sha256.strip().lower()
        path, filename = tracked_file(sha)
        with open(path, "rb") as f:
            data = f.read()
    else:
        raise HTTPException(400, "pick a file or a tracked version")
    if not google_auth.has_scopes(google_auth.DRIVE_SCOPES):
        raise HTTPException(409, "Drive is not authorised yet. Enable the Drive API, then run: python google_auth.py")
    try:
        f = senders.upload_drive_link(filename, data)
    except Exception as e:
        raise HTTPException(502, f"Drive upload failed: {e}")
    return {"link": f["webViewLink"], "drive_file_id": f["id"], "sha256": sha}


@app.post("/api/send/gmail")
def send_gmail(recipient: str = Form(...), subject: str = Form(""), message: str = Form(""), note: str = Form(""),
               confirm: str = Form(""), sha256: Optional[str] = Form(None), modified_at: Optional[str] = Form(None),
               file: Optional[UploadFile] = File(None)):
    """REALLY sends an email with the file attached, then logs the share. Requires confirm=yes."""
    import google_auth
    import senders
    if confirm != "yes":
        raise HTTPException(400, "sending must be confirmed (confirm=yes)")
    to = [a.strip() for a in recipient.split(",") if a.strip()]
    if not to or not all(EMAIL_RE.match(a) for a in to):
        raise HTTPException(400, "enter a valid recipient email address")
    r = None
    if file is not None and file.filename:
        data, filename = file.file.read(), file.filename
        if len(data) > MAX_BYTES:
            raise HTTPException(413, "file is larger than 25 MB (Gmail limit)")
        r = ingest(data, filename, modified_at)
        sha = r["sha256"]
    elif sha256:
        sha = sha256.strip().lower()
        path, filename = tracked_file(sha)
        if os.path.getsize(path) > MAX_BYTES:
            raise HTTPException(413, "file is larger than 25 MB (Gmail limit)")
        with open(path, "rb") as f:
            data = f.read()
    else:
        raise HTTPException(400, "pick a file or a tracked version")
    if not google_auth.has_scopes(google_auth.SEND_SCOPES):
        raise HTTPException(409, "Gmail sending is not authorised yet. Run: python google_auth.py")
    try:
        sent = senders.send_gmail(", ".join(to), subject.strip() or f"Sending: {filename}", message, filename, data)
    except ValueError as e:  # bad header characters etc.
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(502, f"Gmail send failed: {e}")
    out = record_share(sha, "Gmail", ", ".join(to), None, note or "sent from app", bool(r and r["new"]))
    return out | {"sent": True, "gmail_message_id": sent.get("id")}


STOP = set("what which who where when did i do does my me the a an to of on in via for from send sent sending "
           "file files document doc last latest recent recently was were is it that this and with by".split())
ALIAS = {"professor": "prof", "teacher": "prof", "sir": "prof", "faculty": "prof",
         "email": "gmail", "mail": "gmail", "emailed": "gmail", "wa": "whatsapp", "gdrive": "drive",
         "teammates": "teammate", "team": "teammate", "friend": "teammate"}
PLATFORMS = {"gmail", "whatsapp", "drive", "lms"}


def _words(s: str):
    return re.findall(r"[a-z0-9]+", (s or "").lower())


def _hit(tok: str, pieces) -> bool:
    return any(tok == p or (len(tok) >= 3 and p.startswith(tok)) for p in pieces)


@app.get("/api/ask")
def ask(q: str):
    toks = [ALIAS.get(t, t) for t in _words(q) if t not in STOP and len(t) >= 2]
    plats = [t for t in toks if t in PLATFORMS]
    terms = [t for t in toks if t not in PLATFORMS]
    with db.connect() as con:
        rows = con.execute("SELECT s.*, v.filename, v.path, v.modified_at AS v_mod, v.family_id, f.display_name "
                           "FROM shares s JOIN versions v ON v.sha256=s.sha256 "
                           "JOIN families f ON f.id=v.family_id").fetchall()
        best, best_key = None, None
        for r in rows:
            if plats and r["platform"].lower() not in plats:
                continue
            who = _words(r["recipient"])
            what = _words(r["filename"]) + _words(r["display_name"]) + _words(r["note"])
            score = sum(3 for t in terms if _hit(t, who)) + sum(2 for t in terms if _hit(t, what))
            if terms and score == 0:
                continue
            key = (score, r["sent_at"], r["id"])
            if best_key is None or key > best_key:
                best, best_key = r, key
        if not best:
            return {"found": False, "query": q, "message": "No matching send found. Log one with the form below."}
        v = con.execute("SELECT * FROM versions WHERE sha256=?", (best["sha256"],)).fetchone()
        latest = latest_version(con, v["family_id"])
        newer = None
        if is_outdated(v, latest):
            newer = ver(latest) | {"text": f"Newer version exists: {latest['filename']}, edited {fmt(latest['modified_at'])}."}
        now_name = os.path.basename(v["path"] or "")
        renamed = bool(now_name) and not v["path"].startswith("(") and now_name != v["filename"]
        return {
            "found": True, "query": q,
            "message": f"{v['filename']} sent to {best['recipient']} via {best['platform']} on {fmt(best['sent_at'])}",
            "share": share(best), "version": ver(v), "family": {"id": v["family_id"], "name": best["display_name"]},
            "currently_named": now_name if renamed else None,
            "newer": newer,
        }


@app.get("/api/alerts")
def alerts():
    out = []
    with db.connect() as con:
        for f in con.execute("SELECT * FROM families"):
            ls = last_share(con, f["id"])
            if not ls:
                continue
            sent = con.execute("SELECT * FROM versions WHERE sha256=?", (ls["sha256"],)).fetchone()
            latest = latest_version(con, f["id"])
            if is_outdated(sent, latest):
                out.append({"family_id": f["id"], "family_name": f["display_name"], "share": share(ls),
                            "sent_version": ver(sent), "latest_version": ver(latest),
                            "text": f"{f['display_name']}: sent {sent['filename']} to {ls['recipient']} via {ls['platform']} "
                                    f"on {fmt(ls['sent_at'])}, but {latest['filename']} is newer ({fmt(latest['modified_at'])})."})
    return out


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")
