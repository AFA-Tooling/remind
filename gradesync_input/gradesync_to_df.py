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
from google.oauth2.service_account import Credentials
import gspread

# Sheet & credentials config
class_json_name = 'cs10_sp25_test.json'
config_path = os.path.join(os.path.dirname(__file__), 'config/', class_json_name)
with open(config_path, "r") as config_file:
    config = json.load(config_file)

# IDs to link files
SCOPES = config["SCOPES"]
SPREADSHEET_ID = config["SPREADSHEET_ID"]

credentials_json = os.getenv("SERVICE_ACCOUNT_CREDENTIALS")
credentials_dict = json.loads(credentials_json)
credentials = Credentials.from_service_account_info(credentials_dict, scopes=SCOPES)
client = gspread.authorize(credentials)

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
    tab_names = get_all_tab_names(SPREADSHEET_ID, creds)

    for tab in tab_names:
        print(f"\n📄 Parsing tab: {tab}")
        range_str = f"{tab}!A1:Z1000"
        raw_data = get_google_sheet_data(SPREADSHEET_ID, range_str, creds)

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
