"""Seed the local Firestore emulator with fake students for end-to-end testing.

Refuses to run unless Firestore points at a local emulator (see
docs/local-testing.md), so it can never touch production.

Data is written in the CURRENT (one course per student) shape, so you can check
that new code still handles old data before the migration runs. Every date is
relative to today (America/Los_Angeles), so running db_fetch.py right after
seeding always produces the same reminders.

    python services/gradesync_input/seed_emulator.py               # wipe + seed
    python services/gradesync_input/seed_emulator.py --me you@berkeley.edu
    python services/gradesync_input/seed_emulator.py --no-reset     # keep existing data

All seeded students use @example.com addresses (a reserved domain), so nothing
here can reach a real person even if a message is sent by mistake.
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

SERVICES_DIR = Path(__file__).resolve().parent.parent
if str(SERVICES_DIR) not in sys.path:
    sys.path.append(str(SERVICES_DIR))

from shared import settings  # noqa: E402  (sets FIRESTORE_EMULATOR_HOST in emulator mode)
from shared.courses import categorize_assignment, default_category_prefs  # noqa: E402

PROJECT_TZ = ZoneInfo("America/Los_Angeles")
TODAY = datetime.now(PROJECT_TZ).date()

# Students get a reminder exactly this many days before a deadline (the default).
DAYS_BEFORE = 3


def at_due_time(days_from_today: int) -> str:
    """ISO timestamp for 11:59 PM Pacific, N days from today."""
    day = TODAY + timedelta(days=days_from_today)
    return datetime.combine(day, time(23, 59), tzinfo=PROJECT_TZ).isoformat()


def at_release_time(days_from_today: int) -> str:
    day = TODAY + timedelta(days=days_from_today)
    return datetime.combine(day, time(9, 0), tzinfo=PROJECT_TZ).isoformat()


# ---------------------------------------------------------------------------
# Assignments: (course, name, due in N days, released N days from today or None)
# ---------------------------------------------------------------------------
# "Lab 1" exists in BOTH CS61A and CS61C with the same due date on purpose:
# it is the collision case the multi-course work has to handle.
ASSIGNMENTS = [
    ("CS61A", "Lab 1", DAYS_BEFORE, -6),
    ("CS61A", "Lab 2", DAYS_BEFORE, -4),
    ("CS61A", "Homework 3", 7, 0),        # released today → release reminder
    ("CS61A", "Hog", 10, -2),
    ("CS61C", "Lab 1", DAYS_BEFORE, -6),
    ("CS61C", "Project 1", DAYS_BEFORE, -10),
    ("CS10", "Project 2: Spelling Bee", DAYS_BEFORE, -7),
]

# ---------------------------------------------------------------------------
# Students. `intended_courses` is what the multi-course system SHOULD enroll them
# in; in today's shape only the first course can be stored. It is printed as a
# checklist and kept on the seed doc (`_seed_intended_courses`) for later tests.
# ---------------------------------------------------------------------------
STUDENTS: List[Dict[str, Any]] = [
    {
        "email": "alice.multi@example.com",
        "name": "Alice Multi",
        "sid": "3030000001",
        "intended_courses": ["CS61A", "CS61C"],
        "group": 1,
        "missing": [("CS61A", "Lab 1"), ("CS61A", "Lab 2"), ("CS61C", "Lab 1"), ("CS61C", "Project 1")],
        "note": "THE multi-course case. Today: only CS61A reminders. "
                "After the change: CS61A Lab 1 + Lab 2 + Homework 3 (release) AND CS61C Lab 1 + Project 1.",
    },
    {
        "email": "ben.61a@example.com",
        "name": "Ben Single",
        "sid": "3030000002",
        "intended_courses": ["CS61A"],
        "group": 1,
        "missing": [("CS61A", "Lab 2")],
        "submitted": [("CS61A", "Lab 1")],
        "note": "Single course control. Expect CS61A Lab 2 + Homework 3 (release); Lab 1 already submitted.",
    },
    {
        "email": "cara.61c@example.com",
        "name": "Cara NoLabs",
        "sid": "3030000003",
        "intended_courses": ["CS61C"],
        "group": 1,
        "category_prefs_off": ["lab"],
        "missing": [("CS61C", "Lab 1"), ("CS61C", "Project 1")],
        "note": "Turned labs off. Expect CS61C Project 1 only.",
    },
    {
        "email": "dev.waitlist@example.com",
        "name": "Dev Waitlist",
        "sid": "3030000004",
        "intended_courses": ["CS10"],
        "group": 2,
        "missing": [("CS10", "Project 2: Spelling Bee")],
        "note": "Group 2 with CS10 access closed. Expect NO reminder (study gate).",
    },
    {
        "email": "erin.multi.split@example.com",
        "name": "Erin Split",
        "sid": "3030000005",
        "intended_courses": ["CS61C", "CS10"],
        "group": 1,
        "group_by_course": {"CS61C": 1, "CS10": 2},
        "missing": [("CS61C", "Lab 1"), ("CS10", "Project 2: Spelling Bee")],
        "submitted": [("CS61C", "Project 1", "Ungraded")],  # submitted, not graded yet
        "note": "Multi-course, different study groups. After the change: CS61C Lab 1 only "
                "(group 1 there), NOT CS10 (group 2, access closed).",
    },
    {
        "email": "finn.nocourse@example.com",
        "name": "Finn NoCourse",
        "sid": "3030000006",
        "intended_courses": [],
        "group": 1,
        "missing": [],
        "note": "No course at all. Expect an 'unroutable' warning and no reminder.",
    },
]


def submission_doc_id(assignment_name: str, name: str) -> str:
    # Matches upsert_submissions_to_firestore in gradesync_to_db.py (current shape).
    # This ID has no course in it, so Alice's CS61A and CS61C "Lab 1" rows land on
    # the same doc and the second overwrites the first: the same collision the real
    # sync has. Note: a student with NO submission row counts as "missing".
    return f"{assignment_name}__{name}".replace("/", "_").replace(" ", "_")


def build_docs(me: Optional[str]) -> Dict[str, Dict[str, Dict[str, Any]]]:
    now = datetime.now(PROJECT_TZ).isoformat()
    docs: Dict[str, Dict[str, Dict[str, Any]]] = {
        "deadlines": {},
        "assignment_resources": {},
        "students": {},
        "class_roster": {},
        "assignment_submissions": {},
        "study_participants": {},
        "study_config": {},
    }

    for course, name, due_in, released in ASSIGNMENTS:
        docs["deadlines"][f"{course}__{name}".replace("/", "_").replace(" ", "_")] = {
            "course_code": course,
            "assignment_code": name,
            "assignment_name": name,
            "due": at_due_time(due_in),
            "release": at_release_time(released) if released is not None else None,
            "updated_at": now,
        }
        # db_fetch builds its assignment catalog from resources, so every
        # assignment needs at least one resource row to be remindable.
        docs["assignment_resources"][f"{course}__{name}__Assignment_Link".replace(" ", "_").replace(":", "")] = {
            "course_code": course,
            "assignment_code": name,
            "assignment_name": name,
            "resource_type": "Link",
            "resource_name": "Assignment Link",
            "link": f"https://example.com/{course.lower()}/{name.lower().replace(' ', '-')}",
        }

    students = list(STUDENTS)
    if me:
        students.append({
            "email": me.strip().lower(),
            "name": "You (seeded)",
            "sid": "3030009999",
            "intended_courses": ["CS61A", "CS61C"],
            "group": 1,
            "missing": [("CS61A", "Lab 2"), ("CS61C", "Project 1")],
            "note": "Your login, so you can open the dashboard against the emulator. "
                    "Today: CS61A Lab 1 + Lab 2 + Homework 3 (release). After the change: "
                    "also CS61C Lab 1 + Project 1.",
        })

    for s in students:
        email = s["email"]
        courses = s["intended_courses"]
        course = courses[0] if courses else ""  # today's shape holds only one course
        prefs = default_category_prefs(course) if course else {}
        for cat in s.get("category_prefs_off", []):
            prefs[cat] = False

        # Same fields as buildNewStudent in src/api/students/defaults.js, which is
        # also what production student docs hold (no first/last name or SID).
        docs["students"][email] = {
            "email": email,
            "preferred_first_name": s["name"].split(" ")[0],
            "course_code": course,
            "phone_number": None,
            "discord_id": None,
            "days_before_deadline": DAYS_BEFORE,
            "release_reminder": True,
            "project_early_reminder": False,
            "category_prefs": prefs,
            "email_pref": True,
            "phone_pref": False,
            "discord_pref": False,
            "enrolled_via": "consent",
            "welcome_email_sent": True,  # don't trigger a welcome email from the web app
            "_seed_intended_courses": courses,
            "_seed_note": s["note"],
            "created_at": now,
            "updated_at": now,
        }

        if course:
            # Today: one roster doc per email, so the last course synced wins.
            docs["class_roster"][email] = {
                "name": s["name"],
                "email": email,
                "course_code": course,
                "updated_at": now,
            }

        # Today: one participant doc per email, with one course and one group.
        # Production also has consented participants with course_code "" (no
        # course resolved), so a course-less student still gets a participant doc.
        group_by_course = s.get("group_by_course") or {}
        docs["study_participants"][email] = {
            "email": email,
            "course_code": course,
            "group": group_by_course.get(course, s["group"]),
            "source": "csv",
            "_seed_group_by_course": group_by_course or {c: s["group"] for c in courses},
            "created_at": now,
            "updated_at": now,
        }

        # Production status values are "Missing", "Graded" and "Ungraded"; only
        # "Missing" counts as not submitted.
        rows = [(c, a, "Missing") for c, a in s.get("missing", [])]
        rows += [(entry[0], entry[1], entry[2] if len(entry) > 2 else "Graded")
                 for entry in s.get("submitted", [])]
        for course_code, assignment, status in rows:
            docs["assignment_submissions"][submission_doc_id(assignment, s["name"])] = {
                "assignment_name": assignment,
                "category": categorize_assignment(course_code, assignment, mode="ingest"),
                "sid": s["sid"],
                "name": s["name"],
                "email": email,
                "status": status,
                "_seed_course_code": course_code,
                "updated_at": now,
            }

    # Production has access open for every course. CS10 stays closed here so the
    # study gate (Dev, and Erin's CS10 side) still gets exercised.
    for course, access_open in (("CS61A", True), ("CS61C", True), ("CS10", False)):
        docs["study_config"][course] = {"randomized": True, "access_open": access_open, "updated_at": now}

    return docs


def reset_emulator(host: str, project_id: str) -> None:
    """Delete every document in the emulator database (emulator-only REST endpoint)."""
    import requests

    url = f"http://{host}/emulator/v1/projects/{project_id}/databases/(default)/documents"
    resp = requests.delete(url, timeout=30)
    resp.raise_for_status()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--me", help="Also seed your own login email so you can use the dashboard")
    parser.add_argument("--no-reset", action="store_true", help="Don't wipe the emulator first")
    args = parser.parse_args()

    host = settings.require_emulator("seed Firestore")
    project_id = settings.FIREBASE_PROJECT_ID
    if not project_id:
        sys.exit("FIREBASE_PROJECT_ID is not set in .env.local (it must match the emulator's project).")

    # Plain Firestore client: with FIRESTORE_EMULATOR_HOST set it connects to the
    # emulator and needs no credentials.
    from google.cloud import firestore

    db = firestore.Client(project=project_id)

    if not args.no_reset:
        reset_emulator(host, project_id)
        print(f"Wiped emulator data for project '{project_id}' at {host}")

    docs = build_docs(args.me)
    batch = db.batch()
    count = 0
    for collection, by_id in docs.items():
        for doc_id, data in by_id.items():
            batch.set(db.collection(collection).document(doc_id), data)
            count += 1
            if count % 400 == 0:
                batch.commit()
                batch = db.batch()
    batch.commit()

    print(f"Seeded {count} docs: " + ", ".join(f"{c}={len(d)}" for c, d in docs.items()))
    print(f"   Dates are relative to today ({TODAY.isoformat()}, Pacific).\n")
    print("Expected reminders (run: python services/gradesync_input/db_fetch.py):")
    for email, student in docs["students"].items():
        print(f"  - {email}")
        print(f"      intended courses: {student['_seed_intended_courses'] or '(none)'}")
        print(f"      {student['_seed_note']}")
    print("\nKnown limit of today's shape: class_roster, study_participants and")
    print("students can hold only one course each, so multi-course students are seeded")
    print("with their first course only. The rest is in the _seed_* fields.")


if __name__ == "__main__":
    main()
