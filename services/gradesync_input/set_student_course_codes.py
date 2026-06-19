"""
One-off migration: set course_code on students who appear in class_roster.

For each student in the 'students' collection whose email matches a
class_roster entry, this script sets course_code to the value stored
in that roster entry (e.g. "CS61A"). Students not on any roster are
left untouched.
"""

import sys
from pathlib import Path

import firebase_admin
from firebase_admin import credentials, firestore

SERVICES_DIR = Path(__file__).resolve().parent.parent
if str(SERVICES_DIR) not in sys.path:
    sys.path.append(str(SERVICES_DIR))

from shared import settings


def init_firestore() -> firestore.Client:
    if not firebase_admin._apps:
        cred = credentials.Certificate(str(settings.FIREBASE_SERVICE_ACCOUNT_PATH))
        firebase_admin.initialize_app(cred, {"projectId": settings.FIREBASE_PROJECT_ID})
    return firestore.client()


def main():
    db = init_firestore()

    # Build email → course_code map from class_roster
    print("Fetching class_roster...")
    roster_map = {}
    for doc in db.collection("class_roster").stream():
        data = doc.to_dict()
        email = (data.get("email") or doc.id or "").strip().lower()
        course_code = (data.get("course_code") or "").strip()
        if email and course_code:
            roster_map[email] = course_code

    print(f"  Found {len(roster_map)} roster entry/entries across all courses")
    for course, emails in _group_by_course(roster_map).items():
        print(f"  {course}: {len(emails)} student(s)")

    if not roster_map:
        print("No roster entries found. Nothing to do.")
        return

    # Fetch all students and update those whose email is on the roster
    print("\nFetching students...")
    students = list(db.collection("students").stream())
    print(f"  Found {len(students)} student(s)")

    updated = 0
    skipped_no_match = 0
    skipped_already_set = 0

    for doc in students:
        data = doc.to_dict()
        email = (data.get("email") or "").strip().lower()
        course_code = roster_map.get(email)

        if not course_code:
            skipped_no_match += 1
            print(f"  Skipped (not on roster): {email or doc.id}")
            continue

        current = (data.get("course_code") or "").strip()
        if current == course_code:
            skipped_already_set += 1
            print(f"  Already set ({course_code}): {email}")
            continue

        doc.reference.set({"course_code": course_code}, merge=True)
        updated += 1
        print(f"  ✅ Set course_code={course_code} on {email}")

    print(f"\nDone. Updated: {updated}, Already correct: {skipped_already_set}, Not on roster: {skipped_no_match}")


def _group_by_course(roster_map):
    groups = {}
    for email, course in roster_map.items():
        groups.setdefault(course, []).append(email)
    return groups


if __name__ == "__main__":
    main()
