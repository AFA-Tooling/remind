# Setting Up Automated Email Sending

## Problem
The current OAuth 2.0 method requires interactive login every time the token expires, which doesn't work for automated/background processes.

## Solution: Service Account with Domain-Wide Delegation

This allows the service to send emails automatically without any user interaction.

## What You Need

### 1. Google Cloud Project
- A Google Cloud project with Gmail API enabled
- Access to create service accounts

### 2. Google Workspace Account
- Admin access to Google Workspace (for domain-wide delegation)
- A user email to send from (e.g., `autoremind@berkeley.edu`)

### 3. Service Account Credentials
- A service account JSON key file
- Domain-wide delegation enabled
- Authorized in Google Workspace Admin Console

## Quick Setup Checklist

- [ ] Create Google Cloud project
- [ ] Enable Gmail API
- [ ] Create service account
- [ ] Enable domain-wide delegation on service account
- [ ] Download service account JSON key
- [ ] Place JSON key in `email-service/config/AutoRemindCredentials.json`
- [ ] Authorize service account in Google Workspace Admin Console
- [ ] Set `GMAIL_SENDER_EMAIL` environment variable (or pass as parameter)

## Detailed Steps

See `config/README.md` for complete step-by-step instructions.

## How It Works

1. **Service Account**: A special Google account that represents your application
2. **Domain-Wide Delegation**: Allows the service account to act on behalf of any user in your domain
3. **Impersonation**: The service account impersonates the sender email when sending
4. **No Tokens Needed**: Service account credentials don't expire (unlike OAuth tokens)

## Environment Variables

```bash
# Required
GMAIL_CREDENTIALS_PATH="config/AutoRemindCredentials.json"  # Path to service account JSON
GMAIL_SENDER_EMAIL="autoremind@berkeley.edu"                 # Email to send from

# Optional
MESSAGE_REQUESTS_DIR="message_requests"                      # Directory with CSV files
```

## Testing

After setup, test with:

```bash
cd email-service
python main.py
```

The service will:
1. Try to use service account (no interaction needed)
2. Fall back to OAuth if service account fails (requires browser login)

## Troubleshooting

### "Service account authentication failed"
- Check that the JSON file path is correct
- Verify the file is a valid service account JSON
- Ensure domain-wide delegation is enabled on the service account

### "Domain-wide delegation not authorized"
- Go to Google Workspace Admin Console
- Check that the service account Client ID is authorized
- Verify the OAuth scope is: `https://www.googleapis.com/auth/gmail.send`

### "Permission denied" when sending
- Verify the sender email exists in Google Workspace
- Check that domain-wide delegation is properly configured
- Ensure the service account has the correct scopes

## Security Notes

- **Never commit** the service account JSON file to version control
- Store it securely (use environment variables or secret management)
- Rotate keys periodically
- Limit the service account to only necessary scopes

