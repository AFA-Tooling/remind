"""Enroll already-consented students who predate consent-time enrollment.

The daily pipeline iterates the `students` collection, but consenting only ever
wrote a `study_participants` doc. Students who consented and never signed in to the
dashboard therefore received nothing, and those who did sign in landed on the old
registration defaults, which left email off.

This fills both gaps: it creates a student doc for every consented participant
missing one, and turns email on for docs that were created by the old defaults and
never touched since.

An explicit opt-out is never overridden. A student who actually opened the settings
page and saved with email off is reported and left alone — `settings.py` always
stamps a fresh `updated_at` and never writes `created_at`, so a doc whose two
timestamps still match has provably never been through a settings save.

Dry run by default — prints the planned writes and changes nothing. Pass --apply to
commit them.

    python3 services/gradesync_input/backfill_consent_enrollment.py
    python3 services/gradesync_input/backfill_consent_enrollment.py --apply
"""

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

DEFAULT_COURSE_CODE = "CS61A"
STUDENTS_COLLECTION = "students"
ROSTER_COLLECTION = "class_roster"
PARTICIPANTS_COLLECTION = "study_participants"

# Mirrors buildNewStudent in src/api/students/defaults.js. The two runtimes cannot
# share code, so keep them in sync by hand.
DEFAULT_DAYS_BEFORE_DEADLINE = 3
DEFAULT_CATEGORY_PREFS = {
    "lab": True,
    "homework": True,
    "midterm": True,
    "quiz": True,
    "project": True,
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_student_doc(email: str, roster_entry: Dict[str, Any], now: str) -> Dict[str, Any]:
    """Build a student doc for a consented student who has none."""
    name = str(roster_entry.get("name") or "").strip()
    course_code = str(roster_entry.get("course_code") or "").strip() or DEFAULT_COURSE_CODE
    return {
        "email": email,
        "preferred_first_name": name.split(" ")[0] if name else None,
        "course_code": course_code,
        "phone_number": None,
        "discord_id": None,
        "days_before_deadline": DEFAULT_DAYS_BEFORE_DEADLINE,
        "release_reminder": True,
        "project_early_reminder": False,
        "category_prefs": dict(DEFAULT_CATEGORY_PREFS),
        "email_pref": True,
        "phone_pref": False,
        "discord_pref": False,
        "enrolled_via": "consent",
        "created_at": now,
        "updated_at": now,
    }


def never_touched_settings(student: Dict[str, Any]) -> bool:
    """True if this doc was created by registration and never saved from the portal.

    settings.py always writes a fresh `updated_at` and never writes `created_at`, so
    equal timestamps mean no settings save has ever happened. A doc missing either
    field predates the convention; treat that as touched so we never guess wrong in
    the direction of overriding a real choice.
    """
    created = student.get("created_at")
    updated = student.get("updated_at")
    if not created or not updated:
        return False
    return str(created) == str(updated)


def plan_enrollment(
    participants: List[str],
    students: Dict[str, Dict[str, Any]],
    roster: Dict[str, Dict[str, Any]],
    now: str,
) -> Dict[str, List[Any]]:
    """Sort every consented email into exactly one bucket. Pure — no I/O.

    Returns create/activate/skipped_optout lists plus a no_change count.
    """
    create: List[Any] = []
    activate: List[Any] = []
    skipped_optout: List[str] = []
    no_change = 0

    for email in sorted(set(participants)):
        student = students.get(email)

        if student is None:
            create.append((email, build_student_doc(email, roster.get(email) or {}, now)))
            continue

        if student.get("email_pref"):
            no_change += 1
            continue

        if not never_touched_settings(student):
            skipped_optout.append(email)
            continue

        # Only the fields that decide whether email goes out. Anything the student
        # might have set themselves (name, phone, Discord) is left alone.
        activate.append((email, {
            "email_pref": True,
            "days_before_deadline": DEFAULT_DAYS_BEFORE_DEADLINE,
            "category_prefs": dict(DEFAULT_CATEGORY_PREFS),
            "updated_at": now,
        }))

    return {
        "create": create,
        "activate": activate,
        "skipped_optout": skipped_optout,
        "no_change": no_change,
    }


def _load(db):
    participants = [
        str((d.to_dict() or {}).get("email") or d.id).strip().lower()
        for d in db.collection(PARTICIPANTS_COLLECTION).stream()
    ]
    students = {
        str((d.to_dict() or {}).get("email") or d.id).strip().lower(): (d.to_dict() or {})
        for d in db.collection(STUDENTS_COLLECTION).stream()
    }
    roster = {
        str((d.to_dict() or {}).get("email") or d.id).strip().lower(): (d.to_dict() or {})
        for d in db.collection(ROSTER_COLLECTION).stream()
    }
    return participants, students, roster


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Commit the writes (default: dry run)")
    args = parser.parse_args()

    import firebase_admin
    from firebase_admin import credentials, firestore
    from shared import settings

    if not firebase_admin._apps:
        firebase_admin.initialize_app(
            credentials.Certificate(str(settings.FIREBASE_SERVICE_ACCOUNT_PATH)),
            {"projectId": settings.FIREBASE_PROJECT_ID},
        )
    db = firestore.client()

    participants, students, roster = _load(db)
    print(
        f"Loaded {len(participants)} consented participants, "
        f"{len(students)} students, {len(roster)} roster entries.\n"
    )

    plan = plan_enrollment(participants, students, roster, _now_iso())

    if plan["create"]:
        print(f"CREATE — consented, no student doc ({len(plan['create'])}):")
        for email, doc in plan["create"]:
            on_roster = "roster" if email in roster else "default"
            print(f"  {email:42} -> course_code={doc['course_code']}  ({on_roster})")
        print()

    if plan["activate"]:
        print(f"ACTIVATE — student doc exists, email off, never saved settings ({len(plan['activate'])}):")
        for email, _ in plan["activate"]:
            print(f"  {email:42} -> email_pref=True, days_before_deadline={DEFAULT_DAYS_BEFORE_DEADLINE}")
        print()

    if plan["skipped_optout"]:
        print(f"LEFT ALONE — explicit opt-out, saved settings with email off ({len(plan['skipped_optout'])}):")
        for email in plan["skipped_optout"]:
            print(f"  {email}")
        print("  These need a human decision; this script will not override them.\n")

    print(f"{plan['no_change']} student(s) already have email enabled.")

    writes = len(plan["create"]) + len(plan["activate"])
    if not writes:
        print("\nNothing to do — every consented student is already enrolled.")
        return

    print(f"{writes} document(s) would be written.")

    if not args.apply:
        print("\nDRY RUN — nothing written. Re-run with --apply to commit.")
        return

    batch = db.batch()
    pending = 0
    for email, doc in plan["create"]:
        batch.set(db.collection(STUDENTS_COLLECTION).document(email), doc)
        pending += 1
        if pending >= 400:
            batch.commit()
            batch = db.batch()
            pending = 0
    for email, updates in plan["activate"]:
        batch.set(db.collection(STUDENTS_COLLECTION).document(email), updates, merge=True)
        pending += 1
        if pending >= 400:
            batch.commit()
            batch = db.batch()
            pending = 0
    if pending:
        batch.commit()

    print(f"\n✅ Created {len(plan['create'])}, activated {len(plan['activate'])} student doc(s).")


if __name__ == "__main__":
    main()
