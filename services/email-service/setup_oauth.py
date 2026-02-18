#!/usr/bin/env python3
"""
One-time setup script to get OAuth 2.0 refresh token for automated email sending.

This script will:
1. Open a browser for you to log in
2. Get a refresh token that never expires
3. Save it to config/token.json
4. After this, emails will send automatically without any interaction

Usage:
    python setup_oauth.py
"""

import os
import sys
from pathlib import Path

# Add services directory to path to import shared
SERVICES_DIR = Path(__file__).resolve().parent.parent
if str(SERVICES_DIR) not in sys.path:
    sys.path.append(str(SERVICES_DIR))

# Import shared settings
from shared import settings

# Import gmail_service from the same directory
try:
    from gmail_service import get_credentials
except ImportError:
    # If this fails, try to add current directory explicitly (though it should be there)
    sys.path.insert(0, str(Path(__file__).parent))
    from gmail_service import get_credentials

def main():
    print("=" * 60)
    print("OAuth 2.0 Setup for Automated Email Sending")
    print("=" * 60)
    print()
    print("This is a ONE-TIME setup. After this, emails will send automatically.")
    print()
    print("You will need:")
    print(f"  1. OAuth 2.0 credentials file ({settings.OAUTH_CLIENT_SECRET_PATH})")
    print("  2. A browser to log in with the Gmail account you want to send from")
    print()
    
    # Check for credentials file
    credentials_path = settings.OAUTH_CLIENT_SECRET_PATH
    if not credentials_path.exists():
        print(f"❌ Error: Credentials file not found at {credentials_path}")
        print()
        print("Please:")
        print("  1. Go to Google Cloud Console")
        print("  2. Create OAuth 2.0 credentials (Desktop app type)")
        print("  3. Download the JSON file")
        print(f"  4. Place it at {credentials_path}")
        return 1
    
    print(f"✅ Found credentials file: {credentials_path}")
    print()
    print("Starting OAuth flow...")
    print("A browser window will open. Please log in with the Gmail account")
    print("you want to send emails from.")
    print()
    
    token_path = settings.TOKEN_PATH
    
    try:
        # Get credentials (this will open browser for one-time login)
        creds = get_credentials(
            str(credentials_path),
            str(token_path),
            use_service_account=False  # Force OAuth method
        )
        
        if creds and creds.refresh_token:
            print()
            print("=" * 60)
            print("✅ SUCCESS! Setup Complete")
            print("=" * 60)
            print()
            print(f"Refresh token saved to: {token_path}")
            print()
            print("You can now send emails automatically!")
            print("The refresh token will be used to get new access tokens")
            print("whenever needed - no more browser login required.")
            print()
            print("To test, run: python main.py")
            return 0
        else:
            print()
            print("⚠️  Warning: No refresh token received.")
            print("You may need to re-authenticate periodically.")
            return 0
            
    except KeyboardInterrupt:
        print()
        print("❌ Setup cancelled by user")
        return 1
    except Exception as e:
        print()
        print(f"❌ Error during setup: {e}")
        print()
        print("Troubleshooting:")
        print("  - Make sure the credentials file is valid OAuth 2.0 JSON")
        print("  - Check that Gmail API is enabled in Google Cloud Console")
        print("  - Verify the OAuth consent screen is configured")
        return 1

if __name__ == "__main__":
    sys.exit(main())

