"""
Main script to run the Gmail reminder service for AutoRemind.
"""
import os
import sys
import json
import logging
from datetime import datetime
from typing import List, Dict, Any, Optional
from supabase_client import get_supabase_client
from gmail_service import (
    should_send_reminder,
    send_gmail_reminder,
    update_last_sent
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('gmail_reminder.log'),
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)


def parse_datetime(date_string: Optional[str]) -> Optional[datetime]:
    """
    Parse a datetime string from Supabase into a Python datetime object.
    
    Args:
        date_string: ISO format datetime string or None
        
    Returns:
        Datetime object or None
    """
    if not date_string:
        return None
    
    try:
        # Handle ISO format with timezone
        if 'T' in date_string:
            # Remove timezone info if present for simplicity
            date_string = date_string.split('+')[0].split('Z')[0]
        return datetime.fromisoformat(date_string)
    except Exception as e:
        logger.warning(f"Failed to parse datetime '{date_string}': {e}")
        return None


def get_resources_from_student(student: Dict[str, Any]) -> Optional[List[str]]:
    """
    Extract resources from student record.
    
    Args:
        student: Student record dictionary
        
    Returns:
        List of resource links or None
    """
    # Check for common resource field names
    for field_name in ['resources', 'resource_links']:
        if field_name in student and student[field_name]:
            value = student[field_name]
            
            # If it's already a list, return it
            if isinstance(value, list):
                return [str(r).strip() for r in value if r]
            
            # If it's a string, try to parse it
            if isinstance(value, str):
                # Try parsing as JSON first (Supabase might store arrays as JSON strings)
                try:
                    parsed = json.loads(value)
                    if isinstance(parsed, list):
                        return [str(r).strip() for r in parsed if r]
                except (json.JSONDecodeError, TypeError):
                    pass
                
                # If not JSON, try splitting by comma or newline
                return [r.strip() for r in value.replace('\n', ',').split(',') if r.strip()]
    
    return None


def process_student_reminders(
    supabase,
    credentials_path: str = "config/credentials.json",
    sender_email: str = "autoremind@yourdomain.com",
    table_name: str = "autoremind_users"
) -> Dict[str, int]:
    """
    Process all students and send reminders where appropriate.
    
    Args:
        supabase: Supabase client instance
        credentials_path: Path to Google service account credentials
        sender_email: Email address to send from
        table_name: Name of the Supabase table
        
    Returns:
        Dictionary with counts: sent, skipped, errors
    """
    stats = {
        "sent": 0,
        "skipped": 0,
        "errors": 0
    }
    
    try:
        # Fetch all students from Supabase
        logger.info(f"Fetching all students from table '{table_name}'...")
        response = supabase.table(table_name).select("*").execute()
        students = response.data
        
        logger.info(f"Found {len(students)} students in database")
        
        for student in students:
            try:
                # Check if student should receive reminders
                if not student.get('in_autoremind', False):
                    logger.debug(f"Skipping {student.get('student_id')}: in_autoremind is False")
                    stats["skipped"] += 1
                    continue
                
                if not student.get('notify_gmail', False):
                    logger.debug(f"Skipping {student.get('student_id')}: notify_gmail is False")
                    stats["skipped"] += 1
                    continue
                
                if student.get('submitted', False):
                    logger.debug(f"Skipping {student.get('student_id')}: already submitted")
                    stats["skipped"] += 1
                    continue
                
                # Check notification frequency
                last_sent = parse_datetime(student.get('last_reminder_sent'))
                freq_days = student.get('notification_freq_days', 7)  # Default to 7 days
                
                if not should_send_reminder(last_sent, freq_days):
                    logger.debug(
                        f"Skipping {student.get('student_id')}: "
                        f"Only {freq_days - (datetime.now() - last_sent).days} days since last reminder"
                    )
                    stats["skipped"] += 1
                    continue
                
                # Get assignment name and resources
                assignment_name = student.get('assignment_name', 'Assignment')
                resources = get_resources_from_student(student)
                
                # Send reminder
                student_info = {
                    'student_id': student.get('student_id', 'Unknown'),
                    'email': student.get('email')
                }
                
                if not student_info['email']:
                    logger.warning(f"No email found for student {student_info['student_id']}")
                    stats["errors"] += 1
                    continue
                
                success = send_gmail_reminder(
                    student=student_info,
                    assignment_name=assignment_name,
                    resources=resources,
                    credentials_path=credentials_path,
                    sender_email=sender_email
                )
                
                if success:
                    # Update last_reminder_sent in Supabase
                    assignment_id = student.get('assignment_id')
                    update_success = update_last_sent(
                        supabase,
                        student_info['student_id'],
                        assignment_id
                    )
                    
                    if update_success:
                        stats["sent"] += 1
                        logger.info(
                            f"✓ Sent reminder to {student_info['email']} "
                            f"for {assignment_name}"
                        )
                    else:
                        stats["errors"] += 1
                        logger.warning(
                            f"Email sent but failed to update database for "
                            f"{student_info['student_id']}"
                        )
                else:
                    stats["errors"] += 1
                    
            except Exception as e:
                logger.error(f"Error processing student {student.get('student_id', 'unknown')}: {e}")
                stats["errors"] += 1
        
        return stats
        
    except Exception as e:
        logger.error(f"Fatal error in process_student_reminders: {e}")
        raise


def main():
    """
    Main entry point for the Gmail reminder service.
    """
    logger.info("=" * 60)
    logger.info("Starting Gmail Reminder Service for AutoRemind")
    logger.info("=" * 60)
    
    # Get configuration from environment variables
    credentials_path = os.getenv("GMAIL_CREDENTIALS_PATH", "config/credentials.json")
    sender_email = os.getenv("GMAIL_SENDER_EMAIL", "autoremind@yourdomain.com")
    table_name = os.getenv("SUPABASE_TABLE", "autoremind_users")
    
    # Validate credentials file exists
    if not os.path.exists(credentials_path):
        logger.error(f"Credentials file not found: {credentials_path}")
        logger.error("Please set GMAIL_CREDENTIALS_PATH environment variable or place credentials.json in config/")
        sys.exit(1)
    
    try:
        # Initialize Supabase client
        logger.info("Connecting to Supabase...")
        supabase = get_supabase_client()
        logger.info("✓ Connected to Supabase")
        
        # Process reminders
        logger.info("Processing student reminders...")
        stats = process_student_reminders(
            supabase,
            credentials_path=credentials_path,
            sender_email=sender_email,
            table_name=table_name
        )
        
        # Print summary
        logger.info("=" * 60)
        logger.info("Reminder Processing Complete")
        logger.info("=" * 60)
        logger.info(f"Emails sent: {stats['sent']}")
        logger.info(f"Emails skipped: {stats['skipped']}")
        logger.info(f"Errors: {stats['errors']}")
        logger.info("=" * 60)
        
    except ValueError as e:
        logger.error(f"Configuration error: {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()

