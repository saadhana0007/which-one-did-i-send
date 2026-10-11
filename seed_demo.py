"""Generate demo PDFs in ./watched, register them, and seed realistic shares.

Safe to re-run: clears families/versions/shares first (works while the server runs).
Usage: python seed_demo.py
"""
import os
from datetime import datetime, timedelta

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.utils import simpleSplit

import db
import engine
import watcher

WATCH = watcher.WATCH_DIR

ESSAY = """The Impact of Renewable Energy on Urban Infrastructure

Cities around the world are rethinking how they generate and consume power. Solar panels on rooftops, wind turbines at the edge of town and battery storage under parking lots are no longer experiments but practical answers to rising demand. This assignment examines how renewable energy reshapes urban infrastructure, from the electrical grid to public transport and building design.

The first major change is decentralisation. Traditional grids move electricity one way, from a large plant to many homes. Rooftop solar turns households into small producers, so the grid must handle power flowing in both directions. Utilities respond with smart meters, local storage and software that balances supply and demand within minutes.

The second change concerns transport. Electric buses and charging stations connect directly to the power network, and their schedules can be planned around periods when solar output is highest. Cities that coordinate transport and energy planning reduce both emissions and operating costs.

Finally, building codes are evolving. New construction increasingly includes insulation, heat pumps and solar-ready roofs by default. Although these measures raise upfront cost, the long term savings and resilience during outages make a strong case for adoption.

In conclusion, renewable energy is not only a cleaner source of electricity but a catalyst for redesigning the city itself. Careful planning, fair financing and public participation will decide whether the benefits reach every neighbourhood."""

# Each version differs slightly from the previous one (the same essay, small edits).
ESSAY_V2 = ESSAY.replace("rising demand", "rapidly rising demand").replace(
    "Finally, building codes", "Finally, local building codes")
ESSAY_V3 = ESSAY_V2.replace("In conclusion,", "To conclude,").replace(
    "fair financing and public participation", "fair financing, public participation and clear data on outcomes") + (
    "\n\nReferences: International Energy Agency, World Energy Outlook; Urban Sustainability Review, vol. 12.")

RESUME = """Saadhana R
Chennai, India | saadhana@example.com | +91 90000 00000

Objective
Motivated computer science student seeking an internship in software engineering where I can apply my skills in Python, data analysis and web development.

Education
B.E. Computer Science and Engineering, Sri Sivasubramaniya Nadar College of Engineering, expected 2027. CGPA 8.9.

Projects
Image classifier: trained a convolutional network to classify plant diseases with 94 percent accuracy.
Sentiment analysis: built a pipeline that scores product reviews using classical machine learning models.
Home sync: a small tool that keeps files consistent across several personal devices.

Skills
Python, SQL, FastAPI, scikit-learn, PyTorch, Git, HTML and CSS.

Achievements
Finalist in the college hackathon. Member of the coding club and volunteer in the technical events team."""
RESUME_V5 = RESUME.replace("Motivated computer science student", "Motivated final year computer science student").replace(
    "Git, HTML and CSS.", "Git, Docker, HTML and CSS.") + "\n\nCertifications\nDeep Learning Specialization; Google Data Analytics Certificate."


def make_pdf(path, text):
    # invariant=1 -> deterministic bytes, so re-seeding yields identical hashes
    c = canvas.Canvas(str(path), pagesize=A4, invariant=1)
    w, h = A4
    y = h - 60
    for para in text.split("\n"):
        for line in simpleSplit(para, "Helvetica", 11, w - 120) or [""]:
            if y < 60:
                c.showPage()
                y = h - 60
            c.setFont("Helvetica", 11)
            c.drawString(60, y, line)
            y -= 16
    c.save()


def iso(dt):
    return dt.replace(microsecond=0).isoformat()


def main():
    db.init_db()
    with db.connect() as con:
        con.executescript("DELETE FROM shares; DELETE FROM versions; DELETE FROM families;")
        con.execute("DELETE FROM sqlite_sequence")
    WATCH.mkdir(parents=True, exist_ok=True)
    day = (datetime.now() - timedelta(days=3)).replace(hour=0, minute=0, second=0, microsecond=0)  # "recent"
    at = lambda d, hh, mm: day + timedelta(days=d, hours=hh, minutes=mm)

    files = [  # (name, text, mtime)
        ("assignment_final.pdf", ESSAY, at(-1, 18, 30)),
        ("assignment_final2.pdf", ESSAY_V2, at(0, 14, 5)),
        ("assignment_final_latest.pdf", ESSAY_V3, at(0, 21, 40)),
        ("Resume_v3.pdf", RESUME, at(-3, 11, 0)),
        ("Resume_v5.pdf", RESUME_V5, at(1, 9, 15)),
    ]
    sha = {}
    for name, text, mtime in files:
        p = WATCH / name
        make_pdf(p, text)
        ts = mtime.timestamp()
        os.utime(p, (ts, ts))
        sha[name] = engine.register_file(p)["sha256"]

    shares = [
        ("assignment_final.pdf", "WhatsApp", "teammate", at(-1, 19, 2), "Draft for review"),
        ("assignment_final2.pdf", "Gmail", "prof.kumar@ssn.edu.in", at(0, 16, 12), "Assignment submission"),
        ("Resume_v3.pdf", "Gmail", "hr@acme.com", at(-3, 12, 20), "Internship application"),
    ]
    with db.connect() as con:
        for name, platform, who, when, note in shares:
            con.execute("INSERT INTO shares(sha256, platform, recipient, sent_at, note) VALUES (?,?,?,?,?)",
                        (sha[name], platform, who, iso(when), note))
        fams = con.execute("SELECT COUNT(*) FROM families").fetchone()[0]
    print(f"Seeded {len(files)} files into {WATCH} -> {fams} families, {len(shares)} shares.")


if __name__ == "__main__":
    main()
