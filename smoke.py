"""Quick smoke test. Run the server first (and seed_demo.py). Usage: python smoke.py"""
import shutil
import sys
import time
import urllib.parse
from pathlib import Path

import requests

import watcher

B = "http://localhost:8000"
fails = 0


def check(name, cond):
    global fails
    print(("PASS " if cond else "FAIL ") + name)
    fails += not cond


fams = requests.get(B + "/api/families").json()
check("2 families", len(fams) == 2)
check("assignment family has 3 versions", sorted(f["version_count"] for f in fams) == [2, 3])
check("alerts for both families", len(requests.get(B + "/api/alerts").json()) == 2)

ask = lambda q: requests.get(B + "/api/ask", params={"q": q}).json()
a = ask("what did I send to prof")
check("ask prof -> final2 via Gmail", a["found"] and a["version"]["filename"] == "assignment_final2.pdf" and a["share"]["platform"] == "Gmail")
check("newer version flagged", a["newer"] and a["newer"]["filename"] == "assignment_final_latest.pdf")
check("ask whatsapp -> teammate", ask("whatsapp")["share"]["recipient"] == "teammate")
check("ask resume hr", ask("resume to hr")["version"]["filename"] == "Resume_v3.pdf")
check("no match handled", ask("zzzz qqqq")["found"] is False)

src = watcher.WATCH_DIR / "assignment_final2.pdf"
tmp = watcher.WATCH_DIR / "random.pdf"
if src.exists():
    shutil.move(src, tmp)
    time.sleep(3)
    b = ask("what did I send to prof")
    check("rename keeps identity", b["found"] and b["version"]["sha256"] == a["version"]["sha256"])
    check("rename created no new version", sum(f["version_count"] for f in requests.get(B + "/api/families").json()) == 5)
    shutil.move(tmp, src)
    time.sleep(2)
sys.exit(1 if fails else 0)
