"""
Shared delivery logging utility for all notification services.
Logs message delivery attempts to Firestore 'message_delivery_logs' collection.
"""

import logging
from datetime import datetime
from typing import Optional, Dict, Any

import firebase_admin
from firebase_admin import credentials as fb_creds, firestore as fb_firestore

from . import settings

logger = logging.getLogger(__name__)

_db = None


def _get_firestore() -> fb_firestore.Client:
    """Get or initialize Firestore client."""
    global _db
    if _db is not None:
        return _db

    if not firebase_admin._apps:
        sa_path = str(settings.FIREBASE_SERVICE_ACCOUNT_PATH)
        cred = fb_creds.Certificate(sa_path)
        firebase_admin.initialize_app(cred, {
            "projectId": settings.FIREBASE_PROJECT_ID,
        })

    _db = fb_firestore.client()
    return _db


def log_delivery(
    channel: str,
    recipient: str,
    status: str,
    provider_message_id: Optional[str] = None,
    assignment_name: Optional[str] = None,
    course_code: Optional[str] = None,
    recipient_name: Optional[str] = None,
    error_message: Optional[str] = None,
    error_code: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None
) -> Optional[str]:
    """
    Log a message delivery attempt to Firestore.

    Args:
        channel: 'email', 'sms', or 'discord'
        recipient: Email address, phone number, or Discord ID
        status: 'sent' or 'failed'
        provider_message_id: ID from the provider (Gmail, Twilio, Discord)
        assignment_name: Name of the assignment
        course_code: Course code
        recipient_name: Student name
        error_message: Error message if failed
        error_code: Error code if failed
        metadata: Additional data

    Returns:
        Document ID of the created log entry, or None on failure
    """
    try:
        db = _get_firestore()

        log_entry = {
            "channel": channel,
            "recipient": recipient,
            "recipient_name": recipient_name,
            "assignment_name": assignment_name,
            "course_code": course_code,
            "status": status,
            "provider_message_id": provider_message_id,
            "error_message": error_message,
            "error_code": error_code,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "metadata": metadata or {}
        }

        doc_ref = db.collection("message_delivery_logs").add(log_entry)
        doc_id = doc_ref[1].id

        logger.info(f"Logged {channel} delivery: {status} to {recipient} (doc: {doc_id})")
        return doc_id

    except Exception as e:
        logger.error(f"Failed to log delivery: {e}")
        return None


def log_email_delivery(
    recipient: str,
    status: str,
    message_id: Optional[str] = None,
    assignment_name: Optional[str] = None,
    recipient_name: Optional[str] = None,
    error_message: Optional[str] = None,
    **kwargs
) -> Optional[str]:
    """Convenience wrapper for email deliveries."""
    return log_delivery(
        channel="email",
        recipient=recipient,
        status=status,
        provider_message_id=message_id,
        assignment_name=assignment_name,
        recipient_name=recipient_name,
        error_message=error_message,
        **kwargs
    )


def log_sms_delivery(
    recipient: str,
    status: str,
    twilio_sid: Optional[str] = None,
    assignment_name: Optional[str] = None,
    recipient_name: Optional[str] = None,
    error_message: Optional[str] = None,
    error_code: Optional[str] = None,
    **kwargs
) -> Optional[str]:
    """Convenience wrapper for SMS deliveries."""
    return log_delivery(
        channel="sms",
        recipient=recipient,
        status=status,
        provider_message_id=twilio_sid,
        assignment_name=assignment_name,
        recipient_name=recipient_name,
        error_message=error_message,
        error_code=error_code,
        **kwargs
    )


def log_discord_delivery(
    recipient: str,
    status: str,
    discord_message_id: Optional[str] = None,
    assignment_name: Optional[str] = None,
    recipient_name: Optional[str] = None,
    error_message: Optional[str] = None,
    **kwargs
) -> Optional[str]:
    """Convenience wrapper for Discord deliveries."""
    return log_delivery(
        channel="discord",
        recipient=recipient,
        status=status,
        provider_message_id=discord_message_id,
        assignment_name=assignment_name,
        recipient_name=recipient_name,
        error_message=error_message,
        **kwargs
    )
