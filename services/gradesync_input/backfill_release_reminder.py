"""
One-time backfill: opt every registered student into release-day reminders.

Release reminders changed from opt-in to opt-out. Under the old default,
register.js and settings saves wrote `release_reminder: false` for students who
simply never opted in — indistinguishable from a deliberate opt-out. This script
resets `release_reminder` to True for every student doc so the portal shows the
checkbox as marked; students who don't want the notification can uncheck it
(which stores an explicit False that the pipeline respects).

Run once after deploying the opt-out change:

    python3 services/gradesync_input/backfill_release_reminder.py            # dry run
    python3 services/gradesync_input/backfill_release_reminder.py --apply    # write

Idempotent — re-running only touches docs that aren't already True.
"""

import argparse
import sys
from pathlib import Path

import firebase_admin
from firebase_admin import credentials, firestore

SERVICES_DIR = Path(__file__).resolve().parent.parent
if str(SERVICES_DIR) not in sys.path:
    sys.path.append(str(SERVICES_DIR))

from shared import settings


def init_firestore() -> firestore.Client:
    """Initialize Firebase Admin SDK and return a Firestore client."""
    if not firebase_admin._apps:
        sa_path = str(settings.FIREBASE_SERVICE_ACCOUNT_PATH)
        cred = credentials.Certificate(sa_path)
        firebase_admin.initialize_app(cred, {
            "projectId": settings.FIREBASE_PROJECT_ID,
        })
    return firestore.client()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually write changes (default is a dry run that only reports)",
    )
    args = parser.parse_args()

    db = init_firestore()
    docs = list(db.collection("students").stream())

    already_on = 0
    flipped = 0
    for doc in docs:
        data = doc.to_dict() or {}
        if data.get("release_reminder") is True:
            already_on += 1
            continue
        previous = data.get("release_reminder", "<missing>")
        if args.apply:
            doc.reference.set({"release_reminder": True}, merge=True)
        flipped += 1
        print(f"{'✅' if args.apply else '🔎'} {doc.id}: release_reminder {previous} -> True")

    verb = "updated" if args.apply else "would update"
    print(f"\nDone: {verb} {flipped} of {len(docs)} students ({already_on} already opted in).")
    if not args.apply and flipped:
        print("Dry run only — re-run with --apply to write changes.")


if __name__ == "__main__":
    main()
