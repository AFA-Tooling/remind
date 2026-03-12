"""
Load Firestore data into a pandas DataFrame for inspection/debugging.
This replaces the old SQL-based load_data.py that used psycopg2 + Supabase.
"""
import os
import sys
import pandas as pd
from pathlib import Path

# Add services directory to path so we can import shared settings
SERVICES_DIR = Path(__file__).resolve().parent.parent
if str(SERVICES_DIR) not in sys.path:
    sys.path.append(str(SERVICES_DIR))

from shared import settings

import firebase_admin
from firebase_admin import credentials as fb_creds, firestore as fb_firestore


def init_firestore() -> fb_firestore.Client:
    """Initialize Firebase Admin SDK and return a Firestore client."""
    if not firebase_admin._apps:
        sa_path = str(settings.FIREBASE_SERVICE_ACCOUNT_PATH)
        cred = fb_creds.Certificate(sa_path)
        firebase_admin.initialize_app(cred, {
            "projectId": settings.FIREBASE_PROJECT_ID,
        })
    return fb_firestore.client()


def load_collection_to_df(collection_name: str, db: fb_firestore.Client) -> pd.DataFrame:
    """Load all documents from a Firestore collection into a DataFrame."""
    docs = db.collection(collection_name).stream()
    data = [{"_doc_id": doc.id, **doc.to_dict()} for doc in docs]
    if not data:
        print(f"⚠️  No documents found in collection: {collection_name}")
        return pd.DataFrame()
    return pd.DataFrame(data)


def main():
    """Load and display Firestore data."""
    db = init_firestore()
    print("✅ Connected to Firestore!")

    # Load assignment_resources collection (equivalent to the old SQL query)
    df = load_collection_to_df("assignment_resources", db)

    if df.empty:
        print("No data found.")
        return

    # Show selected columns for compatibility with old behavior
    cols_to_show = [
        c for c in ["course_code", "assignment_code", "assignment_name",
                    "resource_type", "resource_name", "link", "deadline"]
        if c in df.columns
    ]
    print(df[cols_to_show] if cols_to_show else df)


if __name__ == "__main__":
    main()
