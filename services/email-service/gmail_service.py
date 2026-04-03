"""
Gmail API service for sending reminder emails.
"""
import os
import base64
import json
import logging
from pathlib import Path
from typing import Optional, List, Dict, Any
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from google.oauth2 import service_account
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
import firebase_admin
from firebase_admin import credentials as fb_creds, firestore as fb_firestore
from email_templates import get_motivating_email_body

# Import shared settings
import sys
import os
# Add services directory to path to import shared
# Assuming this file is at services/email-service/gmail_service.py
# Parent of email-service is services
SERVICES_DIR = Path(__file__).resolve().parent.parent
if str(SERVICES_DIR) not in sys.path:
    sys.path.append(str(SERVICES_DIR))

from shared import settings
from shared.delivery_logger import log_email_delivery

logger = logging.getLogger(__name__)


def format_resources(resources: Optional[List[Any]]) -> str:
    """
    Format a list of resources into a bulleted list string.
    
    Args:
        resources: List of resource objects (with 'link', 'resource_name', 'resource_type') 
                   or simple strings (URLs), or None
        
    Returns:
        Formatted string with bullet points, or empty string if no resources
    """
    if not resources:
        return ""
    
    # Filter out None/empty values
    valid_resources = [r for r in resources if r]
    
    if not valid_resources:
        return ""
    
    formatted_lines = []
    for resource in valid_resources:
        if isinstance(resource, dict):
            # Resource object with name, type, link
            name = resource.get('resource_name', 'Resource')
            resource_type = resource.get('resource_type', '')
            link = resource.get('link', '')
            
            if link:
                if resource_type:
                    formatted_lines.append(f"- {name} [{resource_type}]: {link}")
                else:
                    formatted_lines.append(f"- {name}: {link}")
            else:
                if resource_type:
                    formatted_lines.append(f"- {name} [{resource_type}]")
                else:
                    formatted_lines.append(f"- {name}")
        else:
            # Simple string/URL
            formatted_lines.append(f"- {resource}")
    
    return "\n".join(formatted_lines) if formatted_lines else ""


def _init_firestore() -> fb_firestore.Client:
    """Initialize Firebase Admin SDK and return a Firestore client."""
    if not firebase_admin._apps:
        sa_path = str(settings.FIREBASE_SERVICE_ACCOUNT_PATH)
        cred = fb_creds.Certificate(sa_path)
        firebase_admin.initialize_app(cred, {
            "projectId": settings.FIREBASE_PROJECT_ID,
        })
    return fb_firestore.client()


def extract_assignment_code(assignment_name: str) -> str:
    """
    Extract assignment code from assignment name.
    For "Project 1: Name of Project", returns "Project 1".
    
    Args:
        assignment_name: Full assignment name
        
    Returns:
        Assignment code (everything before the colon), or original name if no colon found
    """
    if not assignment_name:
        return ""
    
    # Split by colon and take the first part
    parts = str(assignment_name).split(":", 1)
    code = parts[0].strip()
    return code if code else assignment_name


def fetch_assignment_resources(
    assignment_code: str,
    course_code: str = "",
    db: Optional[fb_firestore.Client] = None
) -> List[Dict[str, Any]]:
    """
    Fetch assignment resources from Firestore 'assignment_resources' collection.

    Args:
        assignment_code: Assignment code (e.g., "Project 1")
        course_code: Course code (optional)
        db: Optional Firestore client (will create one if not provided)

    Returns:
        List of resource dictionaries with keys: resource_type, resource_name, link
    """
    if not assignment_code:
        return []

    try:
        if db is None:
            db = _init_firestore()

        query = (
            db.collection("assignment_resources")
            .where("assignment_code", "==", assignment_code)
        )
        if course_code:
            query = query.where("course_code", "==", course_code)

        docs = query.stream()
        resources = [
            {k: v for k, v in doc.to_dict().items() if k in ("resource_type", "resource_name", "link")}
            for doc in docs
        ]

        # If no results and no course_code was specified, try without course filter
        if not resources and not course_code:
            logger.debug("No resources found, retrying without course filter...")
            docs = (
                db.collection("assignment_resources")
                .where("assignment_code", "==", assignment_code)
                .stream()
            )
            resources = [
                {k: v for k, v in doc.to_dict().items() if k in ("resource_type", "resource_name", "link")}
                for doc in docs
            ]

        if resources:
            logger.info(
                f"Found {len(resources)} resource(s) for assignment '{assignment_code}' "
                f"(course: '{course_code or 'any'}')"
            )
        else:
            logger.debug(f"No resources found for assignment '{assignment_code}'")

        return resources

    except Exception as e:
        logger.warning(f"Error fetching resources for assignment '{assignment_code}': {e}")
        return []


def get_credentials(
    credentials_path: str, 
    token_path: str = "config/token.json",
    sender_email: str = None,
    use_service_account: bool = True
):
    """
    Get valid credentials for Gmail API.
    
    Supports two authentication methods:
    1. Service Account with Domain-Wide Delegation (recommended for automation)
    2. OAuth 2.0 User Credentials (requires interactive login)
    
    Args:
        credentials_path: Path to credentials JSON file (service account or OAuth client)
        token_path: Path to store/load OAuth token (only used for OAuth method)
        sender_email: Email address to impersonate (required for service account)
        use_service_account: If True, try service account first; if False, use OAuth
        
    Returns:
        Credentials object
    """
    SCOPES = ['https://www.googleapis.com/auth/gmail.send']
    
    # Check if credentials file is service account or OAuth format
    is_service_account = False
    if use_service_account and sender_email:
        try:
            with open(credentials_path, 'r') as f:
                creds_data = json.load(f)
                # Service account files have "type": "service_account"
                # OAuth files have "installed" or "web" keys
                if creds_data.get("type") == "service_account":
                    is_service_account = True
                elif "installed" in creds_data or "web" in creds_data:
                    logger.info("Detected OAuth 2.0 credentials format, skipping service account attempt")
                    is_service_account = False
        except Exception as e:
            logger.debug(f"Could not determine credentials type: {e}")
    
    # Try Service Account method first (for automation)
    if use_service_account and sender_email and is_service_account:
        try:
            logger.info(f"Attempting to use service account with domain-wide delegation...")
            logger.info(f"Impersonating: {sender_email}")
            
            # Load service account credentials
            creds = service_account.Credentials.from_service_account_file(
                credentials_path,
                scopes=SCOPES
            )
            
            # Create delegated credentials to impersonate the sender email
            delegated_creds = creds.with_subject(sender_email)
            
            # Test the credentials by trying to build the service
            # This will fail if domain-wide delegation isn't set up correctly
            test_service = build('gmail', 'v1', credentials=delegated_creds)
            test_service.users().getProfile(userId='me').execute()
            
            logger.info("✅ Successfully authenticated using service account with domain-wide delegation")
            return delegated_creds
            
        except FileNotFoundError:
            logger.warning(f"Service account file not found at {credentials_path}, falling back to OAuth")
        except Exception as e:
            logger.warning(f"Service account authentication failed: {e}")
            logger.warning("Falling back to OAuth 2.0 method...")
            if not use_service_account:
                raise
    
    # Fall back to OAuth 2.0 method (works automatically with refresh tokens)
    logger.info("Using OAuth 2.0 user credentials...")
    creds = None
    
    # Load existing token if available
    if os.path.exists(token_path):
        try:
            creds = Credentials.from_authorized_user_file(token_path, SCOPES)
            logger.info("✅ Loaded existing OAuth token")
        except Exception as e:
            logger.warning(f"Error loading token: {e}")
    
    # If there are no (valid) credentials available, refresh or get new ones
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            logger.info("🔄 Access token expired. Refreshing using refresh token...")
            try:
                creds.refresh(Request())
                logger.info("✅ Successfully refreshed access token")
                # Save refreshed token
                os.makedirs(os.path.dirname(token_path), exist_ok=True)
                with open(token_path, 'w') as token:
                    token.write(creds.to_json())
                logger.info("✅ Refreshed token saved")
            except Exception as e:
                logger.warning(f"❌ Error refreshing token: {e}")
                logger.warning("Refresh token may have been revoked. Need to re-authenticate.")
                creds = None
        
        if not creds:
            logger.info("No valid credentials found. Starting OAuth flow...")
            logger.info("📝 This is a ONE-TIME setup. After this, it will work automatically.")
            logger.info("💡 Tip: For fully automated setup, use service account with domain-wide delegation.")
            flow = InstalledAppFlow.from_client_secrets_file(
                credentials_path, SCOPES)
            creds = flow.run_local_server(port=0)
            logger.info("✅ OAuth authentication successful!")
        
        # Save the credentials for the next run (includes refresh token)
        if creds:
            os.makedirs(os.path.dirname(token_path), exist_ok=True)
            with open(token_path, 'w') as token:
                token.write(creds.to_json())
            logger.info(f"✅ Credentials saved to {token_path}")
            if creds.refresh_token:
                logger.info("✅ Refresh token saved - future runs will be automatic!")
            else:
                logger.warning("⚠️  No refresh token received. You may need to re-authenticate periodically.")
    
    return creds


def create_gmail_service(
    credentials_path: str, 
    sender_email: str, 
    token_path: str = "config/token.json",
    use_service_account: bool = True
):
    """
    Create and return a Gmail API service instance.
    
    Args:
        credentials_path: Path to credentials JSON file (service account or OAuth client)
        sender_email: Email address to send from (required for service account)
        token_path: Path to store/load the OAuth token (only used for OAuth method)
        use_service_account: If True, try service account first; if False, use OAuth
        
    Returns:
        Gmail API service instance
    """
    creds = get_credentials(credentials_path, token_path, sender_email, use_service_account)
    service = build('gmail', 'v1', credentials=creds)
    return service


def create_message(
    sender: str,
    to: str,
    subject: str,
    message_text: str,
    message_html: Optional[str] = None
) -> Dict[str, str]:
    """
    Create a Gmail message object with plain text and optional HTML.

    Args:
        sender: Sender email address
        to: Recipient email address
        subject: Email subject
        message_text: Plain text email body (fallback)
        message_html: HTML email body (optional)

    Returns:
        Dictionary with 'raw' key containing base64-encoded message
    """
    if message_html:
        message = MIMEMultipart('alternative')
        message['to'] = to
        message['from'] = sender
        message['subject'] = subject
        message.attach(MIMEText(message_text, 'plain'))
        message.attach(MIMEText(message_html, 'html'))
    else:
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
    resources: Optional[List[Any]] = None,
    course_code: str = "",
    credentials_path: str = str(settings.OAUTH_CLIENT_SECRET_PATH),
    sender_email: str = None,
    token_path: str = str(settings.TOKEN_PATH)
) -> bool:
    """
    Send a Gmail reminder to a student.
    
    Args:
        student_email: Student email address
        student_name: Student name or ID
        assignment_name: Name of the assignment (e.g., "Project 1: Name of Project")
        resources: Optional list of resource objects or links. If None, will fetch from Supabase.
        course_code: Optional course code for fetching resources from Supabase
        credentials_path: Path to OAuth 2.0 client credentials JSON file
        sender_email: Email address to send from (optional, uses authenticated user if not provided)
        token_path: Path to store/load the OAuth token
        
    Returns:
        True if email was sent successfully, False otherwise
    """
    try:
        # Fetch resources from Firestore if not provided
        if resources is None:
            assignment_code = extract_assignment_code(assignment_name)
            if assignment_code:
                logger.info(f"Fetching resources for assignment code: {assignment_code}")
                resources = fetch_assignment_resources(assignment_code, course_code)
            else:
                logger.warning(f"Could not extract assignment code from: {assignment_name}")
                resources = []
        
        # Create Gmail service
        # Try service account first (for automation), fall back to OAuth if needed
        service = create_gmail_service(credentials_path, sender_email, token_path, use_service_account=True)
        
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
        
        # Create email body using a random motivating template
        email_body = get_motivating_email_body(
            student_name=student_name,
            assignment_name=assignment_name,
            resources_text=resources_text
        )
        
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

        message_id = sent_message.get('id')
        logger.info(
            f"Email sent successfully to {student_email} for {assignment_name}. "
            f"Message ID: {message_id}"
        )

        # Log successful delivery
        log_email_delivery(
            recipient=student_email,
            status="sent",
            message_id=message_id,
            assignment_name=assignment_name,
            recipient_name=student_name
        )

        return True

    except Exception as e:
        logger.error(
            f"Failed to send email to {student_email} "
            f"for {assignment_name}: {str(e)}"
        )

        # Log failed delivery
        log_email_delivery(
            recipient=student_email,
            status="failed",
            assignment_name=assignment_name,
            recipient_name=student_name,
            error_message=str(e)
        )

        return False

