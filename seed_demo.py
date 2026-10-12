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


LAB = """Physics Laboratory Report: Measuring g with a Simple Pendulum

Aim: to determine the acceleration due to gravity using the time period of a simple pendulum.

Apparatus: a metal bob, a cotton thread, a stand with clamp, a stopwatch and a metre scale.

Procedure: the length of the pendulum was measured from the point of suspension to the centre of the bob. The bob was displaced by a small angle and released, and the time for twenty oscillations was recorded. The experiment was repeated for five different lengths and the time period was calculated each time.

Observations: the square of the time period was found to be directly proportional to the length of the pendulum, as expected from theory.

Result: the average value of g obtained from the graph was close to the accepted value, with a small error from timing and measurement of length."""
LAB_V2 = LAB.replace("a small error from timing and measurement of length.",
                     "a small error from timing, air resistance and measurement of length.").replace(
    "Result:", "Calculation: g = 4 pi squared L divided by T squared.\n\nResult:")

PROPOSAL = """Smart Campus Project Proposal

Problem statement: students and staff lose a lot of time finding free classrooms, laboratory slots and parking spaces across the campus. Information is scattered over notice boards, group chats and spreadsheets, and it is often out of date.

Proposed solution: a lightweight web application that shows live room availability, lets faculty book laboratory slots and notifies students about last minute changes. Data is collected from timetable files and a simple check-in screen at each room.

Technology: a Python backend, a small relational database and a responsive web interface that works on any phone.

Timeline: two weeks for the prototype, two weeks for pilot testing in one department and one week for feedback and fixes.

Expected outcome: less wasted time, fewer double bookings and a single trusted source of campus information."""
PROPOSAL_V2 = PROPOSAL.replace("two weeks for the prototype", "two weeks for a working prototype").replace(
    "Expected outcome:", "Budget: the project needs no paid services and can run on existing college servers.\n\nExpected outcome:")
PROPOSAL_V3 = PROPOSAL_V2.replace("Smart Campus Project Proposal", "Smart Campus Project Proposal (Final)").replace(
    "fewer double bookings", "fewer double bookings and measurable savings in daily commute time")

COVER = """Cover Letter

Dear Hiring Manager,

I am writing to apply for the software engineering internship at your company. I am a final year computer science student with hands on experience in Python, web development and data analysis, gained through course projects and a college hackathon.

During my projects I built a plant disease classifier, a review sentiment analyser and a small tool for keeping files consistent across devices. These taught me to break problems into small parts, test early and explain my work clearly to teammates.

I would welcome the chance to contribute to your team and learn from experienced engineers. Thank you for your time and consideration.

Sincerely,
Saadhana R"""
COVER_V2 = COVER.replace("software engineering internship", "software engineering internship starting in January").replace(
    "Thank you for your time and consideration.", "My resume is attached for your reference. Thank you for your time and consideration.")

NOTES = """Data Structures Study Notes: Week 3

Linked lists store elements in nodes, each holding a value and a reference to the next node. Insertion and deletion at the head take constant time, while searching takes linear time because nodes must be visited one by one.

Stacks follow last in first out order and are used for undo operations, expression evaluation and function call management. Queues follow first in first out order and are used in scheduling and breadth first search.

Important points to revise: the difference between arrays and linked lists, how to reverse a linked list in place, and how to implement a queue using two stacks.

Practice questions: detect a cycle in a linked list, merge two sorted lists and evaluate a postfix expression."""
NOTES_V2 = NOTES.replace("Practice questions:", "Tip: draw the pointers on paper before writing code.\n\nPractice questions:").replace(
    "and evaluate a postfix expression.", "evaluate a postfix expression and check balanced brackets with a stack.")

PITCH = """Hackathon Pitch Outline

Opening: everyone has sent the wrong version of a file at least once. A resume with last month's details, an assignment missing the final edits, a report sent before the correction.

Our idea: identify files by what they contain, not what they are called, and remember which version went to whom, on which platform and when.

Demo flow: ask what was sent to the professor, see the answer, see the warning that a newer version exists, rename the file and ask again.

Closing: local first, private by design and ready to extend to more platforms."""


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
        ("lab_report_v1.pdf", LAB, at(-4, 15, 0)),
        ("lab_report_v2.pdf", LAB_V2, at(-2, 9, 30)),
        ("proposal_draft.pdf", PROPOSAL, at(-3, 17, 45)),
        ("proposal_final.pdf", PROPOSAL_V2, at(-1, 11, 10)),
        ("proposal_final_FINAL.pdf", PROPOSAL_V3, at(1, 16, 20)),
        ("cover_letter_techcorp.pdf", COVER, at(-2, 13, 0)),
        ("cover_letter_techcorp_v2.pdf", COVER_V2, at(0, 10, 25)),
        ("ds_notes_week3.pdf", NOTES, at(-1, 20, 15)),
        ("ds_notes_week3_updated.pdf", NOTES_V2, at(1, 18, 0)),
        ("pitch_outline.pdf", PITCH, at(1, 20, 45)),
    ]
    sha = {}
    for name, text, mtime in files:
        p = WATCH / name
        make_pdf(p, text)
        ts = mtime.timestamp()
        os.utime(p, (ts, ts))
        sha[name] = engine.register_file(p)["sha256"]

    shares = [  # (file, platform, recipient, sent_at, note)
        ("assignment_final.pdf", "WhatsApp", "teammate", at(-1, 19, 2), "Draft for review"),
        ("assignment_final2.pdf", "Gmail", "prof.kumar@ssn.edu.in", at(0, 16, 12), "Assignment submission"),
        ("Resume_v3.pdf", "Gmail", "hr@acme.com", at(-3, 12, 20), "Internship application"),
        # lab report: v1 to a lab partner, latest v2 submitted on the LMS -> up to date
        ("lab_report_v1.pdf", "WhatsApp", "Arun (lab partner)", at(-4, 15, 30), "Check my readings"),
        ("lab_report_v2.pdf", "LMS", "Physics Dept LMS", at(-2, 10, 5), "Lab 4 submission"),
        # proposal: draft to a teammate, final to the guide -> FINAL version is newer (outdated)
        ("proposal_draft.pdf", "WhatsApp", "Meera", at(-3, 18, 10), "First draft"),
        ("proposal_final.pdf", "Gmail", "guide@ssn.edu.in", at(-1, 12, 0), "Proposal for approval"),
        # cover letter: latest version sent -> up to date
        ("cover_letter_techcorp_v2.pdf", "Gmail", "careers@techcorp.example", at(0, 11, 0), "Internship application"),
        # notes: old version shared on Drive with the study group -> outdated
        ("ds_notes_week3.pdf", "Drive", "study-group", at(-1, 20, 40), "Shared folder link"),
    ]
    with db.connect() as con:
        for name, platform, who, when, note in shares:
            con.execute("INSERT INTO shares(sha256, platform, recipient, sent_at, note) VALUES (?,?,?,?,?)",
                        (sha[name], platform, who, iso(when), note))
        fams = con.execute("SELECT COUNT(*) FROM families").fetchone()[0]
    print(f"Seeded {len(files)} files into {WATCH} -> {fams} families, {len(shares)} shares.")


if __name__ == "__main__":
    main()
