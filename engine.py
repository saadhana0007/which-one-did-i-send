"""Version engine: hash -> extract text -> MinHash -> family assignment."""
import hashlib
import os
import re
from datetime import datetime

import numpy as np
from datasketch import MinHash

import db

NUM_PERM = 128
THRESHOLD = 0.6
SCHEME = "affine32"  # datasketch>=2 needs the scheme pinned so stored hashes stay comparable
TEXT_EXTS = {".pdf", ".docx", ".txt", ".md"}


def now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


def hash_file(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def extract_text(path) -> str:
    """Best-effort text extraction. Returns '' when unsupported/unreadable."""
    ext = os.path.splitext(str(path))[1].lower()
    try:
        if ext == ".pdf":
            import pdfplumber
            with pdfplumber.open(path) as pdf:
                return "\n".join((p.extract_text() or "") for p in pdf.pages)
        if ext == ".docx":
            import docx
            d = docx.Document(path)
            parts = [p.text for p in d.paragraphs]
            for t in d.tables:
                for row in t.rows:
                    parts.extend(c.text for c in row.cells)
            return "\n".join(parts)
        if ext in (".txt", ".md"):
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                return f.read()
    except Exception as e:  # corrupt / half-written file: fall back to exact hash
        print(f"[engine] text extraction failed for {path}: {e}")
    return ""


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip()


def compute_minhash(text: str):
    """MinHash over word 3-shingles of normalized text; None if there is too little text."""
    words = normalize(text).split(" ")
    if len(words) < 3 or words == [""]:
        return None
    m = MinHash(num_perm=NUM_PERM, scheme=SCHEME)
    for i in range(len(words) - 2):
        m.update(" ".join(words[i:i + 3]).encode("utf-8"))
    return m


def minhash_to_blob(m) -> bytes:
    return m.hashvalues.astype(np.uint64).tobytes()


def minhash_from_blob(b: bytes):
    return MinHash(num_perm=NUM_PERM, scheme=SCHEME, hashvalues=np.frombuffer(b, dtype=np.uint64).copy())


def assign_family(con, mh, filename: str) -> int:
    """Join the most similar family (Jaccard >= THRESHOLD) or create a new one."""
    if mh is not None:
        best_id, best = None, 0.0
        for r in con.execute("SELECT family_id, minhash FROM versions WHERE minhash IS NOT NULL"):
            j = mh.jaccard(minhash_from_blob(r["minhash"]))
            if j > best:
                best_id, best = r["family_id"], j
        if best_id is not None and best >= THRESHOLD:
            return best_id
    cur = con.execute("INSERT INTO families(display_name, created_at) VALUES (?, ?)",
                      (os.path.splitext(filename)[0], now_iso()))
    return cur.lastrowid


def register_file(path, filename=None, modified_at=None, stored_path=None) -> dict:
    """Hash a file and register it as a version (no-op if the hash is already known).

    Returns {sha256, family_id, new}. A renamed/moved file keeps its original
    filename and just gets its path refreshed.
    """
    path = str(path)
    sha = hash_file(path)
    real = stored_path is None
    stored_path = stored_path or os.path.abspath(path)

    def existing(con):
        return con.execute("SELECT family_id FROM versions WHERE sha256=?", (sha,)).fetchone()

    def touch(con):
        if real:  # real on-disk file: refresh path (+ true mtime if we only knew an upload/import date)
            mtime = datetime.fromtimestamp(os.path.getmtime(path)).replace(microsecond=0).isoformat()
            con.execute("UPDATE versions SET path=?, modified_at=CASE WHEN path LIKE '(%' THEN ? "
                        "ELSE modified_at END WHERE sha256=?", (stored_path, mtime, sha))

    with db.connect() as con:
        row = existing(con)
        if row:
            touch(con)
            return {"sha256": sha, "family_id": row["family_id"], "new": False}

    mh = compute_minhash(extract_text(path))  # slow part, outside the write lock
    name = filename or os.path.basename(path)
    mod = modified_at or datetime.fromtimestamp(os.path.getmtime(path)).replace(microsecond=0).isoformat()
    with db.connect() as con:
        con.execute("BEGIN IMMEDIATE")
        row = existing(con)  # another thread/process may have won the race
        if row:
            con.execute("COMMIT")
            return {"sha256": sha, "family_id": row["family_id"], "new": False}
        fid = assign_family(con, mh, name)
        con.execute(
            "INSERT INTO versions(sha256, family_id, filename, path, size, modified_at, minhash, first_seen_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (sha, fid, name, stored_path, os.path.getsize(path), mod,
             minhash_to_blob(mh) if mh is not None else None, now_iso()))
        con.execute("COMMIT")
    print(f"[engine] registered {name} sha={sha[:8]} family={fid}")
    return {"sha256": sha, "family_id": fid, "new": True}
