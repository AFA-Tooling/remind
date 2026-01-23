# Config Directory

Place your Google Cloud service account credentials file here.

## File Required

- `AutoRemindCredentials.json` or `credentials.json` - Google Cloud service account credentials JSON file

## How to Get Credentials for Automated Email Sending

### Step 1: Create Service Account

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create or select a project
3. Enable the **Gmail API**:
   - Go to "APIs & Services" > "Library"
   - Search for "Gmail API"
   - Click "Enable"
4. Go to "IAM & Admin" > "Service Accounts"
5. Click "Create Service Account"
6. Fill in:
   - **Name**: `autoremind-email-sender` (or any name)
   - **Description**: "Service account for sending AutoRemind emails"
7. Click "Create and Continue"
8. Skip role assignment (click "Continue")
9. Click "Done"

### Step 2: Enable Domain-Wide Delegation

1. Click on your newly created service account
2. Click "Show Domain-Wide Delegation" checkbox
3. Note the **Client ID** (you'll need this later)
4. Click "Save"

### Step 3: Create and Download Key

1. In the service account page, go to "Keys" tab
2. Click "Add Key" > "Create new key"
3. Select **JSON** format
4. Click "Create" (file downloads automatically)
5. Rename the downloaded file to `AutoRemindCredentials.json`
6. Place it in this `config/` directory

### Step 4: Configure Domain-Wide Delegation in Google Workspace Admin

**⚠️ IMPORTANT: You need Google Workspace Admin access for this step**

1. Go to [Google Workspace Admin Console](https://admin.google.com/)
2. Navigate to "Security" > "API Controls" > "Domain-wide Delegation"
3. Click "Add new"
4. Fill in:
   - **Client ID**: The Client ID from Step 2
   - **OAuth Scopes**: `https://www.googleapis.com/auth/gmail.send`
5. Click "Authorize"
6. The service account can now send emails on behalf of users in your domain

### Step 5: Authorize Service Account for Sender Email

1. Still in Google Workspace Admin Console
2. Go to "Users" > Find the email you want to send from (e.g., `autoremind@berkeley.edu`)
3. Make sure this user exists and is active
4. The service account will impersonate this user when sending emails

## Alternative: OAuth 2.0 (Not Recommended for Automation)

If you can't set up domain-wide delegation, you can use OAuth 2.0, but it requires:
- Interactive login the first time
- Token refresh (which may fail in automated environments)

To use OAuth instead:
1. Create OAuth 2.0 credentials in Google Cloud Console
2. Download as `credentials.json`
3. The code will automatically detect and use OAuth if service account fails

## Important Notes

- **Service Account method is REQUIRED for automation** - no interactive login needed
- This file contains sensitive credentials and should **NEVER** be committed to version control
- The service account must have domain-wide delegation enabled
- The service account must be authorized in Google Workspace Admin Console
- The sender email must be a valid Google Workspace user
- See the main README.md for detailed usage instructions
