import pandas as pd
import numpy as np
import os
import sys
import argparse
import logging
import json

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
google_sheet_id = '1HGd-7No73YLCHGGB29SrxEJnZ_5SO5oMPY4842d4IAY'
google_sheet_credentials = 'credentials.json'
config_folder = os.path.join(os.path.dirname(__file__), 'config')
credentials_path = os.path.join(config_folder, google_sheet_credentials)

if not os.path.exists(credentials_path):
    logging.error(f"Credentials file not found: {credentials_path}")
    sys.exit(1)

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


def clean_dataframe(df):
    if 'SID' in df.columns:
        df = df[df['SID'].notna()]
        df = df[~df['SID'].astype(str).str.contains("#N/A|UID", na=False)]
    df.columns = df.columns.str.strip()
    for col in df.columns[3:]:
        df[col] = pd.to_numeric(df[col], errors='coerce')
    df.dropna(how='all', inplace=True)
    df.reset_index(drop=True, inplace=True)
    return df

import re
def sanitize_filename(name):
    """
    Replace or remove characters that can't be used in filenames
    """
    # Replace anything not alphanumeric, space, underscore or dash
    name = re.sub(r'[^\w\s-]', '', name)
    return name.strip().replace(' ', '_')


if __name__ == "__main__":
    creds = get_credentials()
    tab_names = get_all_tab_names(google_sheet_id, creds)

    for tab in tab_names:
        print(f"\n📄 Parsing tab: {tab}")
        range_str = f"{tab}!A1:Z1000"
        raw_data = get_google_sheet_data(google_sheet_id, range_str, creds)

        if not raw_data or len(raw_data) < 2:
            print(f"⚠️ Skipping {tab} (no data)")
            continue

        df = convert_to_dataframe(raw_data)
        df = clean_dataframe(df)

        print(df.head())  # Preview the cleaned data
        output_filename = f"{sanitize_filename(tab)}.csv"
        output_path = os.path.join(output_folder, output_filename)
        df.to_csv(output_path, index=False)
        print(f"✅ Saved {output_path}")
        print(f"✅ Saved {tab}.csv")
