import pandas as pd
import numpy as np
import os
import sys
import argparse
import logging
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List

# Create an output folder if it doesn't exist
output_folder = os.path.join(os.path.dirname(__file__), 'output')
if not os.path.exists(output_folder):
    os.makedirs(output_folder)

# Google Sheets API
from googleapiclient.discovery import build
from google.oauth2 import service_account
from google.auth.transport.requests import Request
from google.auth.exceptions import RefreshError

# Firestore (Firebase Admin SDK)
import firebase_admin
from firebase_admin import credentials as fb_credentials, firestore

# Import shared settings
import sys
SERVICES_DIR = Path(__file__).resolve().parent.parent
if str(SERVICES_DIR) not in sys.path:
    sys.path.append(str(SERVICES_DIR))

from shared import settings

# Sheet & credentials config
# OLD test sheet:
#google_sheet_id = '11H0hRtJOHCy59jaxbdRSp7JhDtkaiOibvexZ4Shj4wE'
# Replacing with CS10 Autoreminder ID:
#google_sheet_id = '1tDmN2HREa6SWwcRLzfqdtt_JJxwNPdjLHQevcHl04gQ'
google_sheet_id = '1HPaMeAudhiOXNZ-JfGr5Viw9qpoaZWRn-kAuOX6gGx8'
# google_sheet_credentials = 'credentials.json'
# config_folder = os.path.join(os.path.dirname(__file__), 'config')
# credentials_path = os.path.join(config_folder, google_sheet_credentials)
credentials_path = str(settings.SERVICE_ACCOUNT_PATH)

if not os.path.exists(credentials_path):
    logging.error(f"Credentials file not found: {credentials_path}")
    sys.exit(1)

# Firestore configuration
DEFAULT_FIRESTORE_COLLECTION = "assignment_submissions"
ROSTER_COLLECTION = "class_roster"
ROSTER_COURSE_CODE = "CS61A"

# Tabs that are never assignments
NON_ASSIGNMENT_TABS = {"Sheet1", "Roster"}


def categorize_tab(tab_name: str) -> str:
    """Map a sheet tab name to an assignment category."""
    name = (tab_name or "").strip().lower()
    if name.startswith("lab"):
        return "Lab"
    if name.startswith("homework") or name.startswith("hw"):
        return "Homework"
    if name.startswith("midterm"):
        return "Midterm"
    return "Project"

def safe_filename_for_windows(name: str) -> str:
    """
    Return a Windows-safe filename by replacing ':' and runs of '*' with ' - ', etc
    """
    # Replace ':' with ' - ' and any run of '*' with ' - '
    cleaned = name.replace(":", " - ")
    cleaned = re.sub(r'\*+', ' - ', cleaned)
    # Tidy up spaces and trim trailing spaces/dots
    cleaned = re.sub(r'\s+', ' ', cleaned).strip().rstrip(' .')
    return cleaned

def get_credentials():
    try:
        creds = service_account.Credentials.from_service_account_file(
            credentials_path,
            scopes=['https://www.googleapis.com/auth/spreadsheets.readonly']
        )
        return creds
    except Exception as e:
        logging.error(f"Error getting credentials: {e}")
        sys.exit(1)

def get_all_tab_names(sheet_id, credentials):
    try:
        service = build('sheets', 'v4', credentials=credentials)
        spreadsheet = service.spreadsheets().get(spreadsheetId=sheet_id).execute()
        sheet_metadata = spreadsheet.get('sheets', [])
        tab_names = [sheet['properties']['title'] for sheet in sheet_metadata]
        return tab_names
    except Exception as e:
        logging.error(f"Error fetching tab names: {e}")
        sys.exit(1)

def get_google_sheet_data(sheet_id, range_name, credentials):
    try:
        service = build('sheets', 'v4', credentials=credentials)
        sheet = service.spreadsheets()
        result = sheet.values().get(spreadsheetId=sheet_id, range=range_name).execute()
        return result.get('values', [])
    except Exception as e:
        logging.error(f"Error getting data from Google Sheet: {e}")
        sys.exit(1)

def convert_to_dataframe(data):
    """
    Convert raw sheet data to a cleaned DataFrame, padding short rows
    """
    try:
        headers = data[0]
        rows = data[1:]

        # Pad shorter rows with empty strings to match header length
        padded_rows = [row + [''] * (len(headers) - len(row)) for row in rows]

        df = pd.DataFrame(padded_rows, columns=headers)
        return df
    except Exception as e:
        logging.error(f"Error converting data to DataFrame: {e}")
        sys.exit(1)

def preprocess_df(df, tab_name):
    """
    Cleans and formats a Google Sheets assignment DataFrame:
    - Filters relevant columns
    - Adds an 'assignment' column using the provided tab name
    - Renames columns, reorders them, and standardizes the formatting

    Args:
        df (pd.DataFrame): Raw DataFrame from Google Sheets
        tab_name (str): Name of the Google Sheet tab (used as assignment label)

    Returns:
        pd.DataFrame: Cleaned and formatted DataFrame
    """
    # The Name column is sometimes exported with a stray bytes-literal prefix ("b'Name").
    # Accept either form so sheets from different sources work.
    name_col = "b'Name" if "b'Name" in df.columns else ("Name" if "Name" in df.columns else None)
    if name_col is None:
        raise ValueError("Missing required name column: expected 'Name' or \"b'Name\"")

    required_columns = [name_col, 'SID', 'Email', 'Status', 'Submission Time', 'Lateness (H:M:S)']
    missing = [col for col in required_columns if col not in df.columns]
    if missing:
        raise ValueError(f"Missing columns in input DataFrame: {missing}")

    # Filter and format
    filtered_df = df[required_columns].copy()
    filtered_df['Assignment'] = tab_name
    filtered_df['Category'] = categorize_tab(tab_name)
    filtered_df = filtered_df[['Assignment', 'Category'] + required_columns]
    filtered_df.rename(columns={name_col: 'Name'}, inplace=True)
    filtered_df.columns = filtered_df.columns.str.lower().str.strip()

    return filtered_df


def init_firestore() -> firestore.Client:
    """Initialize Firebase Admin SDK and return a Firestore client."""
    if not firebase_admin._apps:
        sa_path = str(settings.FIREBASE_SERVICE_ACCOUNT_PATH)
        cred = fb_credentials.Certificate(sa_path)
        firebase_admin.initialize_app(cred, {
            "projectId": settings.FIREBASE_PROJECT_ID,
        })
    return firestore.client()






def upsert_submissions_to_firestore(
    df: pd.DataFrame,
    db: firestore.Client,
    collection_name: str
) -> None:
    """
    Upsert assignment submission data to a Firestore collection.

    Args:
        df: DataFrame with columns: assignment, name, sid, email, status
        db: Firestore client instance
        collection_name: Name of the Firestore collection

    Note:
        Document ID is derived from (assignment_name, name) to ensure
        idempotent upserts. Uses set(merge=True) to update existing docs
        or create new ones.
    """
    if df.empty:
        logging.warning("DataFrame is empty, nothing to upsert")
        return

    batch = db.batch()
    batch_size = 0
    total_written = 0

    for _, row in df.iterrows():
        name_value = str(row.get('name', '')).strip() if pd.notna(row.get('name')) else ''
        if not name_value:
            logging.warning(f"Skipping record with missing name for assignment {row.get('assignment', '')}")
            continue

        sid_value = row.get('sid', '')
        if pd.isna(sid_value) or (isinstance(sid_value, str) and sid_value.strip() == ''):
            sid_value = None
        else:
            sid_value = str(sid_value).strip()

        email_value = row.get('email', '')
        if pd.isna(email_value) or (isinstance(email_value, str) and email_value.strip() == ''):
            email_value = None
        else:
            email_value = str(email_value).strip()

        status_value = row.get('status', '')
        if pd.isna(status_value) or (isinstance(status_value, str) and status_value.strip() == ''):
            status_value = None
        else:
            status_value = str(status_value).strip()

        raw_name = str(row.get('assignment', ''))
        assignment_name = re.sub(r'(x[0-9a-f]{2})+', lambda m: bytes.fromhex(m.group().replace('x', '')).decode('utf-8', errors='replace'), raw_name)
        # Composite key: assignment_name + name (underscore-joined, url-safe)
        doc_id = f"{assignment_name}__{name_value}".replace('/', '_').replace(' ', '_')

        category_value = row.get('category', '')
        if pd.isna(category_value) or (isinstance(category_value, str) and category_value.strip() == ''):
            category_value = categorize_tab(assignment_name)
        else:
            category_value = str(category_value).strip()

        record = {
            'assignment_name': assignment_name,
            'category': category_value,
            'sid': sid_value,
            'name': name_value,
            'email': email_value,
            'status': status_value,
            'updated_at': datetime.now().isoformat()
        }

        doc_ref = db.collection(collection_name).document(doc_id)
        batch.set(doc_ref, record, merge=True)
        batch_size += 1
        total_written += 1

        # Firestore batch limit is 500 writes
        if batch_size >= 499:
            batch.commit()
            batch = db.batch()
            batch_size = 0

    if batch_size > 0:
        batch.commit()

    print(f"✅ Successfully upserted {total_written} records to '{collection_name}'")


def sync_roster_to_firestore(
    raw_data: List[List[str]],
    db: firestore.Client,
    course_code: str = ROSTER_COURSE_CODE,
    collection_name: str = ROSTER_COLLECTION,
) -> None:
    """
    Sync the Roster tab to a Firestore collection of enrolled students.

    Roster tab columns: Name, SID, Email, Role. Only Name + Email are used.
    Documents are keyed by lowercased email. Prior roster docs for this
    course_code that are no longer in the sheet are deleted so dropped
    students don't keep getting category-gated reminders.
    """
    if not raw_data or len(raw_data) < 2:
        print("⚠️  Roster tab is empty or missing — skipping roster sync")
        return

    headers = [str(h).strip().lower() for h in raw_data[0]]
    try:
        name_idx = headers.index("name")
        email_idx = headers.index("email")
    except ValueError:
        print(f"❌ Roster tab missing 'Name' or 'Email' column (got {headers}). Skipping.")
        return

    current_emails: set = set()
    batch = db.batch()
    batch_size = 0
    total_written = 0

    for row in raw_data[1:]:
        if len(row) <= max(name_idx, email_idx):
            continue
        name = str(row[name_idx]).strip()
        email_raw = str(row[email_idx]).strip()
        if not email_raw:
            continue
        email_lower = email_raw.lower()
        current_emails.add(email_lower)

        doc_ref = db.collection(collection_name).document(email_lower)
        batch.set(doc_ref, {
            "name": name,
            "email": email_raw,
            "course_code": course_code,
            "updated_at": datetime.now().isoformat(),
        }, merge=True)
        batch_size += 1
        total_written += 1

        if batch_size >= 499:
            batch.commit()
            batch = db.batch()
            batch_size = 0

    if batch_size > 0:
        batch.commit()

    # Prune stale roster entries for this course
    existing_docs = db.collection(collection_name).where("course_code", "==", course_code).stream()
    prune_batch = db.batch()
    prune_size = 0
    pruned = 0
    for doc in existing_docs:
        if doc.id not in current_emails:
            prune_batch.delete(doc.reference)
            prune_size += 1
            pruned += 1
            if prune_size >= 499:
                prune_batch.commit()
                prune_batch = db.batch()
                prune_size = 0
    if prune_size > 0:
        prune_batch.commit()

    print(f"✅ Roster synced: {total_written} enrolled, {pruned} pruned (course={course_code})")


if __name__ == "__main__":
    # Parse command-line arguments
    parser = argparse.ArgumentParser(
        description="Fetch assignment data from Google Sheets and upload to Firestore"
    )
    parser.add_argument(
        "--firestore",
        action="store_true",
        default=True,
        help="Enable Firestore upload (default: True)"
    )
    parser.add_argument(
        "--no-firestore",
        dest="firestore",
        action="store_false",
        help="Disable Firestore upload"
    )
    parser.add_argument(
        "--csv-fallback",
        action="store_true",
        help="Also write CSV files for debugging"
    )
    parser.add_argument(
        "--collection",
        default=DEFAULT_FIRESTORE_COLLECTION,
        help=f"Firestore collection name (default: {DEFAULT_FIRESTORE_COLLECTION})"
    )
    parser.add_argument(
        "--test",
        action="store_true",
        help="Test mode: process only the first valid assignment tab"
    )
    args = parser.parse_args()
    
    # Initialize Google Sheets credentials
    creds = get_credentials()
    tab_names = get_all_tab_names(google_sheet_id, creds)

    # Initialize Firestore client if enabled
    db_client = None
    if args.firestore:
        try:
            db_client = init_firestore()
            print("✅ Connected to Firestore")
        except Exception as e:
            logging.error(f"Failed to initialize Firestore: {e}")
            if not args.csv_fallback:
                print("❌ Firestore upload required but credentials not available. Exiting.")
                sys.exit(1)
            else:
                print("⚠️  Firestore upload disabled, falling back to CSV only")
                args.firestore = False

    processed_count = 0
    
    for tab in tab_names:
        if tab == "Roster":
            if args.firestore and db_client:
                print(f"\n Parsing tab: {tab} (roster sync)")
                roster_data = get_google_sheet_data(google_sheet_id, tab, creds)
                try:
                    sync_roster_to_firestore(roster_data, db_client)
                except Exception as e:
                    logging.error(f"Error syncing roster: {e}")
                    print(f"❌ Failed to sync roster. Continuing.")
            else:
                print(f"Skipping {tab} (firestore disabled)")
            continue

        if tab in NON_ASSIGNMENT_TABS:
            print(f"Skipping {tab} (non-assignment tab)")
            continue

        category = categorize_tab(tab)
        print(f"\n Parsing tab: {tab} (category={category})")
        range_str = f"{tab}"
        raw_data = get_google_sheet_data(google_sheet_id, range_str, creds)

        if not raw_data or len(raw_data) < 2:
            print(f"Skipping {tab} (no data)")
            continue
        
        try:
            # 1. Convert the raw data to a dataframe
            df = convert_to_dataframe(raw_data)

            # 2. Preprocess the dataframe
            df = preprocess_df(df, tab)
            print(f"Cleaned {tab} DataFrame:")
            print(df.head())  # Preview the cleaned data

            # 3. Upload to Firestore (if enabled)
            if args.firestore and db_client:
                try:
                    upsert_submissions_to_firestore(
                        df,
                        db_client,
                        args.collection
                    )
                    processed_count += 1
                    print(f"✅ Successfully processed {tab}")
                except Exception as e:
                    logging.error(f"Error uploading {tab} to Firestore: {e}")
                    if not args.csv_fallback:
                        print(f"❌ Failed to upload {tab} to Firestore. Continuing with next tab...")
                        continue

            # 4. Export to CSV (if fallback enabled or Firestore disabled)
            if args.csv_fallback or not args.firestore:
                output_filename = f"{safe_filename_for_windows(tab)}.csv"
                output_path = os.path.join(output_folder, output_filename)

                # ✅ Ensure the folder exists
                os.makedirs(os.path.dirname(output_path), exist_ok=True)

                # Save the CSV
                df.to_csv(output_path, index=False)
                print(f"Saved {output_path}")
                print(f"Saved {tab}.csv")
                processed_count += 1
            
            # If in test mode, break after processing first valid assignment
            if args.test:
                print(f"\n🧪 Test mode: Processed 1 assignment ({tab}). Exiting.")
                break
                
        except Exception as e:
            logging.error(f"Error processing tab {tab}: {e}")
            print(f"❌ Failed to process {tab}. Continuing with next tab...")
            continue
