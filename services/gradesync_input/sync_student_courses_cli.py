#!/usr/bin/env python3
"""CLI: sync students.course_code from class_roster.

    python3 services/gradesync_input/sync_student_courses_cli.py
    python3 services/gradesync_input/sync_student_courses_cli.py --apply
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import firebase_admin
from firebase_admin import credentials, firestore

SERVICES_DIR = Path(__file__).resolve().parent.parent
if str(SERVICES_DIR) not in sys.path:
    sys.path.append(str(SERVICES_DIR))

from shared import settings
from sync_student_courses import sync_students_from_roster


def init_firestore() -> firestore.Client:
    if not firebase_admin._apps:
        cred = credentials.Certificate(str(settings.FIREBASE_SERVICE_ACCOUNT_PATH))
        firebase_admin.initialize_app(cred, {"projectId": settings.FIREBASE_PROJECT_ID})
    return firestore.client()


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync student course_code from class_roster")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write changes (default is dry-run)",
    )
    args = parser.parse_args()

    db = init_firestore()
    dry_run = not args.apply
    print(f"{'DRY RUN — ' if dry_run else ''}Syncing student course codes from roster…")
    updated, already_ok, not_on_roster = sync_students_from_roster(db, dry_run=dry_run)
    print(
        f"Done. Updated: {updated}, Already correct: {already_ok}, "
        f"Not on roster: {not_on_roster}"
    )
    if dry_run and updated:
        print("Re-run with --apply to write changes.")


if __name__ == "__main__":
    main()
