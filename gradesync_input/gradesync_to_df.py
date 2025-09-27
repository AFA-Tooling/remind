import pandas as pd
import numpy as np
import os
import sys
import argparse
import logging
import json
import re

# Create an output folder if it doesn't exist
output_folder = os.path.join(os.path.dirname(__file__), 'output')
if not os.path.exists(output_folder):
    os.makedirs(output_folder)

# Google Sheets API
from googleapiclient.discovery import build
from google.oauth2 import service_account
from google.auth.transport.requests import Request
from google.auth.exceptions import RefreshError

# Sheet & credentials config
google_sheet_id = '11H0hRtJOHCy59jaxbdRSp7JhDtkaiOibvexZ4Shj4wE'
google_sheet_credentials = 'credentials.json'
config_folder = os.path.join(os.path.dirname(__file__), 'config')
credentials_path = os.path.join(config_folder, google_sheet_credentials)

if not os.path.exists(credentials_path):
    logging.error(f"Credentials file not found: {credentials_path}")
    sys.exit(1)

def safe_filename_for_windows(name: str) -> str:
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
    required_columns = ["b'First Name", 'Last Name', 'SID', 'Email', 'Status', 'Submission Time', 'Lateness (H:M:S)']
    missing = [col for col in required_columns if col not in df.columns]
    if missing:
        raise ValueError(f"Missing columns in input DataFrame: {missing}")
    
    # Filter and format
    filtered_df = df[required_columns].copy()
    filtered_df['Assignment'] = tab_name
    filtered_df = filtered_df[['Assignment'] + required_columns]
    filtered_df.rename(columns={"b'First Name": 'First Name'}, inplace=True)
    filtered_df.columns = filtered_df.columns.str.lower().str.strip()

    return filtered_df


if __name__ == "__main__":
    creds = get_credentials()
    tab_names = get_all_tab_names(google_sheet_id, creds)

    for tab in tab_names:

        # Skip the summary tabs
        if tab in ['Roster', 'Labs', 'Discussions', 'Projects', 'Lecture Quizzes', 'Midterms', 'Postterms']:
            print(f"Skipping {tab} (not relevant)")
            continue

        print(f"\n Parsing tab: {tab}")
        range_str = f"{tab}"
        raw_data = get_google_sheet_data(google_sheet_id, range_str, creds)

        if not raw_data or len(raw_data) < 2:
            print(f"Skipping {tab} (no data)")
            continue
        
        # 1. Convert the raw data to a dataframe
        df = convert_to_dataframe(raw_data)

        # 2. Preprocess the dataframe
        df = preprocess_df(df, tab)
        print(f"Cleaned {tab} DataFrame:")
        print(df.head())  # Preview the cleaned data

        # 3. Export the cleaned dataframe to CSV
        output_filename = f"{safe_filename_for_windows(tab)}.csv"
        output_path = os.path.join(output_folder, output_filename)

        # ✅ Ensure the folder exists
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        # Save the CSV
        df.to_csv(output_path, index=False)
        print(f"Saved {output_path}")
        print(f"Saved {tab}.csv")
