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

# Supabase
from dotenv import load_dotenv
from supabase import Client, create_client

# Sheet & credentials config
# OLD test sheet:
#google_sheet_id = '11H0hRtJOHCy59jaxbdRSp7JhDtkaiOibvexZ4Shj4wE'
# Replacing with CS10 Autoreminder ID:
google_sheet_id = '1jQLrBjhSDbzARCHCQCVinnFqJxmT0OmenjdhcnxIm2s'
google_sheet_credentials = 'credentials.json'
config_folder = os.path.join(os.path.dirname(__file__), 'config')
credentials_path = os.path.join(config_folder, google_sheet_credentials)

if not os.path.exists(credentials_path):
    logging.error(f"Credentials file not found: {credentials_path}")
    sys.exit(1)

# Supabase configuration
DEFAULT_SUPABASE_TABLE = "assignment_submissions"

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
    #required_columns = ["b'First Name", 'Last Name', 'SID', 'Email', 'Status', 'Submission Time', 'Lateness (H:M:S)']
    required_columns = ["b'Name", 'SID', 'Email', 'Status', 'Submission Time', 'Lateness (H:M:S)']
    missing = [col for col in required_columns if col not in df.columns]
    if missing:
        raise ValueError(f"Missing columns in input DataFrame: {missing}")
    
    # Filter and format
    filtered_df = df[required_columns].copy()
    filtered_df['Assignment'] = tab_name
    filtered_df = filtered_df[['Assignment'] + required_columns]
    #filtered_df.rename(columns={"b'First Name": 'First Name'}, inplace=True)
    filtered_df.rename(columns={"b'Name": 'Name'}, inplace=True)
    filtered_df.columns = filtered_df.columns.str.lower().str.strip()

    return filtered_df


def load_supabase_env() -> Dict[str, str]:
    """
    Load Supabase environment variables from .env file.
    Returns a dictionary with 'url' and 'service_role_key'.
    """
    env_path = Path(__file__).resolve().parent / ".env"
    load_dotenv(env_path)

    required_vars = ["SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY"]
    missing = [var for var in required_vars if not os.getenv(var)]

    if missing:
        raise ValueError(
            "Missing required environment variables: " + ", ".join(missing)
        )

    return {
        "url": os.environ["SUPABASE_URL"],
        "service_role_key": os.environ["SUPABASE_SERVICE_ROLE_KEY"],
    }






def upsert_submissions_to_supabase(
    df: pd.DataFrame,
    supabase: Client,
    table_name: str
) -> None:
    """
    Upsert assignment submission data to Supabase table.
    
    Args:
        df: DataFrame with columns: assignment, name, sid, email, status
        supabase: Supabase client instance
        table_name: Name of the Supabase table
    
    Note:
        Primary key is (assignment_name, name). Records with missing names
        will be skipped with a warning. Uses upsert to update existing records
        or insert new ones.
    """
    if df.empty:
        logging.warning("DataFrame is empty, nothing to upsert")
        return
    
    # Prepare records for upsert
    records: List[Dict[str, Any]] = []
    
    for _, row in df.iterrows():
        # Build record
        # Note: name is required (part of primary key), so ensure it's not None
        name_value = str(row.get('name', '')).strip() if pd.notna(row.get('name')) else ''
        if not name_value:
            logging.warning(f"Skipping record with missing name for assignment {row.get('assignment', '')}")
            continue
        
        # Handle SID - convert empty strings to None
        sid_value = row.get('sid', '')
        if pd.isna(sid_value) or (isinstance(sid_value, str) and sid_value.strip() == ''):
            sid_value = None
        else:
            sid_value = str(sid_value).strip()
        
        # Handle email - convert empty strings to None
        email_value = row.get('email', '')
        if pd.isna(email_value) or (isinstance(email_value, str) and email_value.strip() == ''):
            email_value = None
        else:
            email_value = str(email_value).strip()
        
        # Handle status - convert empty strings to None
        status_value = row.get('status', '')
        if pd.isna(status_value) or (isinstance(status_value, str) and status_value.strip() == ''):
            status_value = None
        else:
            status_value = str(status_value).strip()
        
        record = {
            'assignment_name': str(row.get('assignment', '')),
            'sid': sid_value,
            'name': name_value,
            'email': email_value,
            'status': status_value,
            'updated_at': datetime.now().isoformat()
        }
        
        records.append(record)
    
    if not records:
        logging.warning("No valid records to upsert")
        return
    
    try:
        # Upsert with conflict resolution on (assignment_name, name)
        # The upsert method will update existing records or insert new ones
        # based on the primary key constraint (assignment_name, name)
        response = supabase.table(table_name).upsert(records).execute()
        
        if hasattr(response, 'error') and response.error:
            raise RuntimeError(f"Supabase error: {response.error}")
        
        print(f"✅ Successfully upserted {len(records)} records to {table_name}")
        
    except Exception as e:
        logging.error(f"Error upserting to Supabase: {e}")
        raise


if __name__ == "__main__":
    # Parse command-line arguments
    parser = argparse.ArgumentParser(
        description="Fetch assignment data from Google Sheets and upload to Supabase"
    )
    parser.add_argument(
        "--supabase",
        action="store_true",
        default=True,
        help="Enable Supabase upload (default: True)"
    )
    parser.add_argument(
        "--no-supabase",
        dest="supabase",
        action="store_false",
        help="Disable Supabase upload"
    )
    parser.add_argument(
        "--csv-fallback",
        action="store_true",
        help="Also write CSV files for debugging"
    )
    parser.add_argument(
        "--table",
        default=DEFAULT_SUPABASE_TABLE,
        help=f"Supabase table name (default: {DEFAULT_SUPABASE_TABLE})"
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
    
    # Initialize Supabase client if enabled
    supabase_client = None
    if args.supabase:
        try:
            supabase_config = load_supabase_env()
            supabase_client = create_client(
                supabase_config["url"],
                supabase_config["service_role_key"]
            )
            print("✅ Connected to Supabase")
        except ValueError as e:
            logging.error(f"Failed to load Supabase credentials: {e}")
            if not args.csv_fallback:
                print("❌ Supabase upload required but credentials not available. Exiting.")
                sys.exit(1)
            else:
                print("⚠️  Supabase upload disabled, falling back to CSV only")
                args.supabase = False

    processed_count = 0
    
    for tab in tab_names:
        # Skip the summary tabs
        if tab in ['Roster', 'Labs', 'Discussions', 'Projects', 'Lecture Quizzes', 'Midterms', 'Postterms']:
            print(f"Skipping {tab} (summary tab)")
            continue
        
        # Only process tabs that start with "Project" (case-insensitive)
        if not tab.lower().startswith('project'):
            print(f"Skipping {tab} (not a Project)")
            continue

        print(f"\n Parsing tab: {tab}")
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

            # 3. Upload to Supabase (if enabled)
            if args.supabase and supabase_client:
                try:
                    upsert_submissions_to_supabase(
                        df,
                        supabase_client,
                        args.table
                    )
                    processed_count += 1
                    print(f"✅ Successfully processed {tab}")
                except Exception as e:
                    logging.error(f"Error uploading {tab} to Supabase: {e}")
                    if not args.csv_fallback:
                        print(f"❌ Failed to upload {tab} to Supabase. Continuing with next tab...")
                        continue

            # 4. Export to CSV (if fallback enabled or Supabase disabled)
            if args.csv_fallback or not args.supabase:
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
