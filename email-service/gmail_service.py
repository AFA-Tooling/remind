"""
Gmail API service for sending reminder emails.
"""
import os
import base64
import json
import logging
from typing import Optional, List, Dict, Any
from email.mime.text import MIMEText
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

logger = logging.getLogger(__name__)


def format_resources(resources: Optional[List[str]]) -> str:
    """
    Format a list of resource links into a bulleted list string.
    
    Args:
        resources: List of resource URLs/links, or None
        
    Returns:
        Formatted string with bullet points, or empty string if no resources
    """
    if not resources:
        return ""
    
    # Filter out None/empty values
    valid_resources = [r for r in resources if r]
    
    if not valid_resources:
        return ""
    
    return "\n".join([f"- {resource}" for resource in valid_resources])


def get_credentials(credentials_path: str, token_path: str = "config/token.json"):
    """
    Get valid user credentials from storage or run OAuth flow.
    
    Args:
        credentials_path: Path to OAuth 2.0 client credentials JSON file
        token_path: Path to store/load the token
        
    Returns:
        Credentials object
    """
    SCOPES = ['https://www.googleapis.com/auth/gmail.send']
    creds = None
    
    # Load existing token if available
    if os.path.exists(token_path):
        try:
            creds = Credentials.from_authorized_user_file(token_path, SCOPES)
        except Exception as e:
            logger.warning(f"Error loading token: {e}")
    
    # If there are no (valid) credentials available, let the user log in
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            logger.info("Refreshing expired token...")
            try:
                creds.refresh(Request())
            except Exception as e:
                logger.warning(f"Error refreshing token: {e}, will re-authenticate")
                creds = None
        
        if not creds:
            logger.info("No valid credentials found. Starting OAuth flow...")
            flow = InstalledAppFlow.from_client_secrets_file(
                credentials_path, SCOPES)
            creds = flow.run_local_server(port=0)
        
        # Save the credentials for the next run
        os.makedirs(os.path.dirname(token_path), exist_ok=True)
        with open(token_path, 'w') as token:
            token.write(creds.to_json())
        logger.info(f"Credentials saved to {token_path}")
    
    return creds


def create_gmail_service(credentials_path: str, sender_email: str, token_path: str = "config/token.json"):
    """
    Create and return a Gmail API service instance.
    
    Args:
        credentials_path: Path to OAuth 2.0 client credentials JSON file
        sender_email: Email address to send from (user must authorize this)
        token_path: Path to store/load the OAuth token
        
    Returns:
        Gmail API service instance
    """
    creds = get_credentials(credentials_path, token_path)
    service = build('gmail', 'v1', credentials=creds)
    return service


def create_message(sender: str, to: str, subject: str, message_text: str) -> Dict[str, str]:
    """
    Create a Gmail message object.
    
    Args:
        sender: Sender email address
        to: Recipient email address
        subject: Email subject
        message_text: Email body text
        
    Returns:
        Dictionary with 'raw' key containing base64-encoded message
    """
    message = MIMEText(message_text)
    message['to'] = to
    message['from'] = sender
    message['subject'] = subject
    
    raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode()
    return {'raw': raw_message}


def send_gmail_reminder(
    student_email: str,
    student_name: str,
    assignment_name: str,
    resources: Optional[List[str]] = None,
    credentials_path: str = "config/AutoRemindCredentials.json",
    sender_email: str = None,
    token_path: str = "config/token.json"
) -> bool:
    """
    Send a Gmail reminder to a student.
    
    Args:
        student_email: Student email address
        student_name: Student name or ID
        assignment_name: Name of the assignment
        resources: Optional list of resource links
        credentials_path: Path to OAuth 2.0 client credentials JSON file
        sender_email: Email address to send from (optional, uses authenticated user if not provided)
        token_path: Path to store/load the OAuth token
        
    Returns:
        True if email was sent successfully, False otherwise
    """
    try:
        # Create Gmail service
        service = create_gmail_service(credentials_path, sender_email, token_path)
        
        # Get sender email - try to get from profile, but if that fails,
        # Gmail will automatically use the authenticated user's email when sending
        actual_sender = sender_email
        if not actual_sender:
            try:
                # Try to get profile to know the sender email (requires gmail.readonly scope)
                # But if we don't have that scope, Gmail will still send from authenticated user
                profile = service.users().getProfile(userId='me').execute()
                actual_sender = profile.get('emailAddress')
                logger.info(f"Using authenticated email: {actual_sender}")
            except Exception as e:
                # If we can't get profile, that's okay - Gmail will use authenticated user's email
                logger.info("Using authenticated user's email (profile access not available)")
                # Use a placeholder - Gmail will replace it with the actual authenticated email
                actual_sender = "noreply@autoremind.com"
        
        # Format resources
        resources_text = format_resources(resources)
        
        # Create email body
        email_body = f"""Hi {student_name},

You still have "{assignment_name}" pending. Here are some resources that might help:
{resources_text if resources_text else "No resources available at this time."}

You've got this! 💪

– The AutoRemind Team"""
        
        # Create subject
        subject = f"Reminder: {assignment_name} is due soon!"
        
        # Create and send message
        # Note: When using userId='me', Gmail automatically sets From to authenticated user's email
        message = create_message(
            sender=actual_sender,
            to=student_email,
            subject=subject,
            message_text=email_body
        )
        
        sent_message = service.users().messages().send(
            userId='me',
            body=message
        ).execute()
        
        logger.info(
            f"Email sent successfully to {student_email} for {assignment_name}. "
            f"Message ID: {sent_message.get('id')}"
        )
        
        return True
        
    except Exception as e:
        logger.error(
            f"Failed to send email to {student_email} "
            f"for {assignment_name}: {str(e)}"
        )
        return False

