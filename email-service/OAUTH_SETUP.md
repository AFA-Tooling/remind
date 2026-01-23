# Sending Emails Without Domain-Wide Delegation

## Option 1: OAuth 2.0 with Refresh Tokens (Recommended Alternative)

This method requires **one-time interactive login**, then works automatically forever (as long as the refresh token is valid).

### How It Works

1. **First Time**: Interactive login in browser (one-time setup)
2. **Gets Refresh Token**: Google provides a refresh token that doesn't expire
3. **Automatic Refresh**: Code automatically uses refresh token to get new access tokens
4. **No More Interaction**: Works automatically in background/cron jobs

### Setup Steps

#### 1. Create OAuth 2.0 Credentials

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create or select a project
3. Enable **Gmail API**
4. Go to "APIs & Services" > "Credentials"
5. Click "Create Credentials" > "OAuth client ID"
6. Choose "Desktop app" (or "Web application" if deploying)
7. Download the JSON file
8. Place it in `email-service/config/AutoRemindCredentials.json`

#### 2. Get Refresh Token (One-Time Setup)

Run this **once** to get the refresh token:

```bash
cd email-service
python -c "
from gmail_service import get_credentials
creds = get_credentials('config/AutoRemindCredentials.json', 'config/token.json', use_service_account=False)
print('✅ Refresh token saved! You can now use this automatically.')
"
```

This will:
- Open a browser window
- Ask you to log in with the Gmail account you want to send from
- Save the refresh token to `config/token.json`
- **Never ask you to log in again** (unless refresh token is revoked)

#### 3. Use Automatically

After the one-time setup, the code will:
- Load the refresh token from `config/token.json`
- Automatically refresh access tokens when they expire
- Work in background/cron jobs without any interaction

### Important Notes

- **Refresh tokens can be revoked** if:
  - User changes password
  - User revokes access in Google Account settings
  - Token hasn't been used for 6 months
- **One-time setup required** - you need to run the initial login once
- **Works for any Gmail account** - personal or Workspace
- **No admin access needed** - just the account you want to send from

---

## Option 2: SMTP with App Passwords (Personal Gmail Only)

**⚠️ Only works for personal Gmail accounts, NOT Google Workspace**

### Setup

1. Enable 2-Factor Authentication on your Gmail account
2. Generate an App Password:
   - Go to [Google Account Settings](https://myaccount.google.com/)
   - Security > 2-Step Verification > App passwords
   - Generate password for "Mail"
3. Use SMTP instead of Gmail API

### Limitations

- Only works for personal Gmail (@gmail.com)
- Doesn't work for Google Workspace accounts
- Less secure than OAuth
- Requires 2FA enabled

---

## Option 3: Service Account (Requires Domain-Wide Delegation)

This is what we set up earlier - requires Google Workspace Admin access.

---

## Comparison

| Method | Setup Complexity | Works Automatically | Works for Workspace | Admin Access Needed |
|--------|-----------------|---------------------|---------------------|---------------------|
| OAuth 2.0 + Refresh Token | Medium (one-time login) | ✅ Yes | ✅ Yes | ❌ No |
| SMTP + App Password | Easy | ✅ Yes | ❌ No (personal only) | ❌ No |
| Service Account | Hard (admin setup) | ✅ Yes | ✅ Yes | ✅ Yes |

---

## Recommended: OAuth 2.0 with Refresh Tokens

For your use case (automated sending without admin access), **OAuth 2.0 with refresh tokens** is the best option:

✅ One-time setup (interactive login once)  
✅ Works automatically forever  
✅ Works for Google Workspace accounts  
✅ No admin access required  
✅ More secure than SMTP  

The code already supports this - just make sure to:
1. Get the refresh token once (run the setup script)
2. Keep `config/token.json` secure (it contains the refresh token)
3. The code will automatically refresh access tokens as needed

