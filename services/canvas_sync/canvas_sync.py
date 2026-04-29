"""
Sync Canvas assignments for all connected users into Firestore.

Run as part of the daily pipeline (Step 0) or standalone:
    python3 services/canvas_sync/canvas_sync.py
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

import firebase_admin
from firebase_admin import credentials, firestore

# Add services to path
SERVICES_DIR = Path(__file__).resolve().parent.parent
if str(SERVICES_DIR) not in sys.path:
    sys.path.append(str(SERVICES_DIR))

from shared import settings
from canvas_client import canvas_fetch, refresh_access_token

# Refresh tokens 5 minutes before expiry
REFRESH_BUFFER_SECONDS = 5 * 60


def init_firestore() -> firestore.Client:
    """Initialize Firebase and return Firestore client."""
    if not firebase_admin._apps:
        cred = credentials.Certificate(str(settings.FIREBASE_SERVICE_ACCOUNT_PATH))
        firebase_admin.initialize_app(cred, {"projectId": settings.FIREBASE_PROJECT_ID})
    return firestore.client()


def get_valid_token(db: firestore.Client, email: str, token_doc: Dict[str, Any]) -> str:
    """Return a valid access token, refreshing if needed."""
    expires_at = datetime.fromisoformat(token_doc["token_expires_at"].replace("Z", "+00:00"))
    now = datetime.now(timezone.utc)

    if (expires_at - now).total_seconds() > REFRESH_BUFFER_SECONDS:
        return token_doc["access_token"]

    # Refresh
    token_data = refresh_access_token(
        token_doc["canvas_domain"],
        settings.CANVAS_CLIENT_ID,
        settings.CANVAS_CLIENT_SECRET,
        token_doc["refresh_token"],
    )

    new_expires = datetime.now(timezone.utc).isoformat()
    expires_in = token_data.get("expires_in", 3600)
    from datetime import timedelta
    new_expires_at = (datetime.now(timezone.utc) + timedelta(seconds=expires_in)).isoformat()

    update_data = {
        "access_token": token_data["access_token"],
        "token_expires_at": new_expires_at,
    }
    if "refresh_token" in token_data:
        update_data["refresh_token"] = token_data["refresh_token"]

    db.collection("canvas_tokens").document(email).update(update_data)
    return token_data["access_token"]


def sync_user(db: firestore.Client, email: str, token_doc: Dict[str, Any]) -> Dict[str, int]:
    """Sync Canvas assignments for a single user. Returns counts."""
    domain = token_doc["canvas_domain"]
    access_token = get_valid_token(db, email, token_doc)

    # Fetch active student courses
    courses = canvas_fetch(domain, access_token,
        "/courses?enrollment_state=active&enrollment_type=student")

    deadline_docs: list[tuple[str, Dict[str, Any]]] = []

    for course in courses:
        try:
            assignments = canvas_fetch(domain, access_token,
                f"/courses/{course['id']}/assignments?include[]=submission&order_by=due_at")
        except Exception as e:
            print(f"  Warning: Failed to fetch assignments for course {course.get('id')}: {e}")
            continue

        for assignment in assignments:
            if not assignment.get("due_at"):
                continue

            submission = assignment.get("submission") or {}
            doc_id = f"{email}__{assignment['id']}"

            deadline_docs.append((doc_id, {
                "email": email,
                "canvas_assignment_id": assignment["id"],
                "canvas_course_id": course["id"],
                "course_code": course.get("course_code") or course.get("name") or f"Course {course['id']}",
                "course_name": course.get("name", ""),
                "assignment_name": assignment["name"],
                "due": assignment["due_at"],
                "html_url": assignment.get("html_url", ""),
                "submission_state": submission.get("workflow_state", "unsubmitted"),
                "is_missing": submission.get("missing", False),
                "source": "canvas",
                "synced_at": datetime.now(timezone.utc).isoformat(),
            }))

    # Batch write
    collection = db.collection("canvas_deadlines")
    for i in range(0, len(deadline_docs), 500):
        batch = db.batch()
        for doc_id, data in deadline_docs[i:i + 500]:
            batch.set(collection.document(doc_id), data)
        batch.commit()

    # Remove stale docs
    current_ids = {doc_id for doc_id, _ in deadline_docs}
    existing = collection.where("email", "==", email).stream()
    stale_ids = [doc.id for doc in existing if doc.id not in current_ids]

    for i in range(0, len(stale_ids), 500):
        batch = db.batch()
        for doc_id in stale_ids[i:i + 500]:
            batch.delete(collection.document(doc_id))
        batch.commit()

    # Update sync timestamp
    db.collection("canvas_tokens").document(email).update({
        "last_sync_at": datetime.now(timezone.utc).isoformat(),
        "sync_error": None,
    })

    return {"synced": len(deadline_docs), "removed": len(stale_ids)}


def sync_all_users(db: firestore.Client) -> None:
    """Sync Canvas data for all connected users."""
    tokens_snap = db.collection("canvas_tokens").stream()
    token_docs = [(doc.id, doc.to_dict()) for doc in tokens_snap]

    if not token_docs:
        print("No Canvas-connected users found. Skipping Canvas sync.")
        return

    print(f"Syncing Canvas assignments for {len(token_docs)} user(s)...")

    for email, token_doc in token_docs:
        try:
            result = sync_user(db, email, token_doc)
            print(f"  {email}: synced {result['synced']} assignments, removed {result['removed']} stale")
        except Exception as e:
            print(f"  {email}: sync failed - {e}")
            try:
                db.collection("canvas_tokens").document(email).update({
                    "sync_error": str(e),
                })
            except Exception:
                pass


def main():
    print("Connecting to Firestore for Canvas sync...")
    db = init_firestore()
    sync_all_users(db)
    print("Canvas sync complete.")


if __name__ == "__main__":
    main()
