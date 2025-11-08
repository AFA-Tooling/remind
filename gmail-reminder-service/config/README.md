# Config Directory

Place your Google Cloud service account credentials file here.

## File Required

- `credentials.json` - Google Cloud service account credentials JSON file

## How to Get Credentials

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create or select a project
3. Enable the Gmail API
4. Go to "IAM & Admin" > "Service Accounts"
5. Create a new service account or select an existing one
6. Create a key (JSON format) and download it
7. Place the downloaded file here as `credentials.json`

## Important Notes

- This file contains sensitive credentials and should NEVER be committed to version control
- The service account must have domain-wide delegation enabled
- The service account must be authorized to send emails from the sender email address
- See the main README.md for detailed setup instructions

