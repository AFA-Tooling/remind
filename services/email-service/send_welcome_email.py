#!/usr/bin/env python3
"""
Standalone script to send welcome emails to new AutoRemind users.
Called from Node.js via subprocess with JSON argument.

Usage:
    python send_welcome_email.py '{"email": "...", "preferred_name": "...", ...}'

Returns JSON to stdout:
    {"success": true} or {"success": false, "error": "..."}
"""

import sys
import json
import logging
from pathlib import Path

# Set up path for imports
SERVICES_DIR = Path(__file__).resolve().parent.parent
if str(SERVICES_DIR) not in sys.path:
    sys.path.append(str(SERVICES_DIR))

from shared import settings
from gmail_service import create_gmail_service, create_message

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def format_channels_summary(channels: dict) -> str:
    """Format the channels summary for the welcome email."""
    enabled = []

    if channels.get('email', {}).get('enabled'):
        enabled.append("- Email notifications")

    if channels.get('sms', {}).get('enabled'):
        phone = channels.get('sms', {}).get('value', '')
        if phone:
            enabled.append(f"- SMS notifications to {phone}")
        else:
            enabled.append("- SMS notifications")

    if channels.get('discord', {}).get('enabled'):
        discord_id = channels.get('discord', {}).get('value', '')
        if discord_id:
            enabled.append(f"- Discord notifications (ID: {discord_id})")
        else:
            enabled.append("- Discord notifications")

    if not enabled:
        return "No notification channels enabled yet."

    return "\n".join(enabled)


def create_welcome_email_body(user_data: dict) -> str:
    """Create the welcome email body from user data."""
    preferred_name = user_data.get('preferred_name', 'there')
    channels = user_data.get('channels', {})
    days_before = user_data.get('days_before', 1)

    channels_summary = format_channels_summary(channels)

    email_body = f"""Hi {preferred_name}!

Welcome to AutoRemind! We're excited to help you stay on top of your assignments.

Here's a summary of your notification preferences:

NOTIFICATION CHANNELS:
{channels_summary}

TIMING:
You'll receive reminders {days_before} day(s) before each deadline.

WHAT HAPPENS NEXT:
When you have an upcoming assignment, we'll send you a friendly reminder
so you never miss a deadline.

You can update these preferences anytime by visiting our settings page.

Best,
The AutoRemind Team
"""
    return email_body


def send_welcome_email(user_data: dict) -> dict:
    """
    Send a welcome email to a new user.

    Args:
        user_data: Dictionary containing:
            - email: User's email address
            - preferred_name: User's preferred name
            - channels: Dict of channel preferences (email, sms, discord)
            - days_before: Number of days before deadline for reminders

    Returns:
        Dictionary with 'success' and optionally 'error' keys
    """
    try:
        email = user_data.get('email')
        if not email:
            return {"success": False, "error": "No email address provided"}

        preferred_name = user_data.get('preferred_name', 'there')

        # Create Gmail service
        service = create_gmail_service(
            credentials_path=str(settings.OAUTH_CLIENT_SECRET_PATH),
            sender_email=None,
            token_path=str(settings.TOKEN_PATH),
            use_service_account=True
        )

        # Get sender email from profile
        sender_email = None
        try:
            profile = service.users().getProfile(userId='me').execute()
            sender_email = profile.get('emailAddress')
            logger.info(f"Using authenticated email: {sender_email}")
        except Exception as e:
            logger.info("Using authenticated user's email (profile access not available)")
            sender_email = "noreply@autoremind.com"

        # Create email content
        subject = "Welcome to AutoRemind!"
        email_body = create_welcome_email_body(user_data)

        # Create and send message
        message = create_message(
            sender=sender_email,
            to=email,
            subject=subject,
            message_text=email_body
        )

        sent_message = service.users().messages().send(
            userId='me',
            body=message
        ).execute()

        logger.info(
            f"Welcome email sent successfully to {email}. "
            f"Message ID: {sent_message.get('id')}"
        )

        return {"success": True}

    except Exception as e:
        error_msg = str(e)
        logger.error(f"Failed to send welcome email to {user_data.get('email')}: {error_msg}")
        return {"success": False, "error": error_msg}


def main():
    """Main entry point - parse JSON argument and send email."""
    if len(sys.argv) < 2:
        result = {"success": False, "error": "No user data provided"}
        print(json.dumps(result))
        sys.exit(1)

    try:
        user_data = json.loads(sys.argv[1])
    except json.JSONDecodeError as e:
        result = {"success": False, "error": f"Invalid JSON: {str(e)}"}
        print(json.dumps(result))
        sys.exit(1)

    result = send_welcome_email(user_data)
    print(json.dumps(result))
    sys.exit(0 if result.get("success") else 1)


if __name__ == "__main__":
    main()
