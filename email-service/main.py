"""
Main script to run the Gmail reminder service for AutoRemind.
Reads message request CSV files and sends Gmail reminders.
"""
import os
import sys
import argparse
import logging
import pandas as pd
from pathlib import Path
from typing import Dict, List
from gmail_service import send_gmail_reminder

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


def get_student_name(row: Dict) -> str:
    """
    Extract student name from CSV row.
    Handles both 'name' column and 'first name'/'last name' columns.
    
    Args:
        row: CSV row dictionary
        
    Returns:
        Student name string
    """
    # Check for 'name' column first
    if 'name' in row and pd.notna(row['name']) and row['name'].strip():
        return str(row['name']).strip()
    
    # Check for 'first name' and 'last name' columns
    first_name = row.get('first name', '')
    last_name = row.get('last name', '')
    
    if pd.notna(first_name) and pd.notna(last_name):
        return f"{first_name} {last_name}".strip()
    elif pd.notna(first_name):
        return str(first_name).strip()
    elif pd.notna(last_name):
        return str(last_name).strip()
    
    # Fallback to student_id or email
    if 'sid' in row and pd.notna(row['sid']):
        return str(row['sid'])
    elif 'email' in row:
        return str(row['email']).split('@')[0]
    
    return "Student"


def process_message_request_file(
    file_path: Path,
    credentials_path: str = "config/AutoRemindCredentials.json",
    sender_email: str = "autoremind@yourdomain.com",
    resources: List[str] = None
) -> Dict[str, int]:
    """
    Process a single message request CSV file and send Gmail reminders.
    
    Args:
        file_path: Path to the message request CSV file
        credentials_path: Path to Google service account credentials
        sender_email: Email address to send from
        resources: Optional list of resource links for all students
        
    Returns:
        Dictionary with counts: sent, skipped, errors
    """
    stats = {
        "sent": 0,
        "skipped": 0,
        "errors": 0
    }
    
    try:
        logger.info(f"Processing file: {file_path.name}")
        
        # Read CSV file
        df = pd.read_csv(file_path)
        
        if df.empty:
            logger.warning(f"File {file_path.name} is empty")
            return stats
        
        logger.info(f"Found {len(df)} students in {file_path.name}")
        
        # Process each row
        for index, row in df.iterrows():
            try:
                # Extract required fields
                email = row.get('email')
                assignment = row.get('assignment', 'Assignment')
                
                # Skip if no email
                if pd.isna(email) or not str(email).strip():
                    logger.warning(f"Row {index + 1}: No email address, skipping")
                    stats["skipped"] += 1
                    continue
                
                email = str(email).strip()
                
                # Get student name
                student_name = get_student_name(row)
                
                # Send reminder
                success = send_gmail_reminder(
                    student_email=email,
                    student_name=student_name,
                    assignment_name=assignment,
                    resources=resources,
                    credentials_path=credentials_path,
                    sender_email=sender_email,
                    token_path="config/token.json"
                )
                
                if success:
                    stats["sent"] += 1
                    logger.info(f"✓ Sent reminder to {email} for {assignment}")
                else:
                    stats["errors"] += 1
                    
            except Exception as e:
                logger.error(f"Error processing row {index + 1} in {file_path.name}: {e}")
                stats["errors"] += 1
        
        return stats
        
    except Exception as e:
        logger.error(f"Error processing file {file_path.name}: {e}")
        stats["errors"] += len(df) if 'df' in locals() else 0
        return stats


def process_all_message_requests(
    message_requests_dir: str = None,
    credentials_path: str = "config/AutoRemindCredentials.json",
    sender_email: str = "autoremind@yourdomain.com",
    resources: List[str] = None,
    specific_file: str = None
) -> Dict[str, int]:
    """
    Process message request CSV files. Can process a specific file or all files in a directory.
    
    Args:
        message_requests_dir: Directory containing message request CSV files (defaults to ../gradesync_input/message_requests)
        credentials_path: Path to Google service account credentials
        sender_email: Email address to send from
        resources: Optional list of resource links
        specific_file: If provided, process only this specific file path
        
    Returns:
        Dictionary with total counts: sent, skipped, errors
    """
    total_stats = {
        "sent": 0,
        "skipped": 0,
        "errors": 0
    }
    
    base_dir = Path(__file__).parent
    
    # If specific file is provided, process only that file
    if specific_file:
        csv_file = Path(specific_file)
        if not csv_file.is_absolute():
            # Try relative to email-service first
            csv_file = base_dir / specific_file
            # If not found, try relative to gradesync_input/message_requests
            if not csv_file.exists():
                csv_file = base_dir.parent / "gradesync_input" / "message_requests" / specific_file
            # If still not found, try just the filename in gradesync_input/message_requests
            if not csv_file.exists():
                csv_file = base_dir.parent / "gradesync_input" / "message_requests" / Path(specific_file).name
        
        if not csv_file.exists():
            logger.error(f"File not found: {csv_file}")
            logger.error(f"Tried: {base_dir / specific_file}")
            logger.error(f"Tried: {base_dir.parent / 'gradesync_input' / 'message_requests' / specific_file}")
            return total_stats
        
        logger.info(f"Processing specific file: {csv_file.name}")
        file_stats = process_message_request_file(
            csv_file,
            credentials_path=credentials_path,
            sender_email=sender_email,
            resources=resources
        )
        
        for key in total_stats:
            total_stats[key] += file_stats[key]
        
        logger.info(f"Completed {csv_file.name}: {file_stats['sent']} sent, "
                   f"{file_stats['skipped']} skipped, {file_stats['errors']} errors")
        
        return total_stats
    
    # Otherwise, process all files in directory
    # Default to gradesync_input/message_requests if not specified
    if message_requests_dir is None:
        # Default to ../gradesync_input/message_requests relative to email-service
        requests_dir = base_dir.parent / "gradesync_input" / "message_requests"
    else:
        requests_dir = base_dir / message_requests_dir if not Path(message_requests_dir).is_absolute() else Path(message_requests_dir)
    
    if not requests_dir.exists():
        logger.error(f"Message requests directory not found: {requests_dir}")
        return total_stats
    
    # Find all CSV files
    csv_files = list(requests_dir.glob("*.csv"))
    
    if not csv_files:
        logger.warning(f"No CSV files found in {requests_dir}")
        return total_stats
    
    logger.info(f"Found {len(csv_files)} message request file(s)")
    
    # Process each file
    for csv_file in csv_files:
        file_stats = process_message_request_file(
            csv_file,
            credentials_path=credentials_path,
            sender_email=sender_email,
            resources=resources
        )
        
        # Aggregate stats
        for key in total_stats:
            total_stats[key] += file_stats[key]
        
        logger.info(f"Completed {csv_file.name}: {file_stats['sent']} sent, "
                   f"{file_stats['skipped']} skipped, {file_stats['errors']} errors")
    
    return total_stats


def main():
    """
    Main entry point for the Gmail reminder service.
    """
    parser = argparse.ArgumentParser(
        description="Send Gmail reminders from message request CSV files"
    )
    parser.add_argument(
        "--file",
        "-f",
        type=str,
        help="Process a specific CSV file (path relative to email-service or absolute path)"
    )
    parser.add_argument(
        "--dir",
        "-d",
        type=str,
        help="Directory containing message request CSV files (defaults to ../gradesync_input/message_requests)"
    )
    parser.add_argument(
        "--credentials",
        "-c",
        type=str,
        help="Path to Google service account credentials JSON file (defaults to config/AutoRemindCredentials.json)"
    )
    parser.add_argument(
        "--sender",
        "-s",
        type=str,
        help="Email address to send from (defaults to autoremind@yourdomain.com)"
    )
    
    args = parser.parse_args()
    
    logger.info("=" * 60)
    logger.info("Starting Gmail Reminder Service for AutoRemind")
    logger.info("=" * 60)
    
    # Get configuration from command line args or environment variables
    credentials_path = args.credentials or os.getenv("GMAIL_CREDENTIALS_PATH", "config/AutoRemindCredentials.json")
    sender_email = args.sender or os.getenv("GMAIL_SENDER_EMAIL", "autoremind@yourdomain.com")
    message_requests_dir = args.dir or os.getenv("MESSAGE_REQUESTS_DIR")
    specific_file = args.file
    
    # Validate credentials file exists
    base_dir = Path(__file__).parent
    if Path(credentials_path).is_absolute():
        creds_path = Path(credentials_path)
    else:
        creds_path = base_dir / credentials_path
    
    if not creds_path.exists():
        logger.error(f"Credentials file not found: {creds_path}")
        logger.error("Please set GMAIL_CREDENTIALS_PATH environment variable or place AutoRemindCredentials.json in config/")
        sys.exit(1)
    
    try:
        # Process message request files
        if specific_file:
            logger.info(f"Processing specific file: {specific_file}")
        else:
            logger.info("Processing all message request files...")
        
        stats = process_all_message_requests(
            message_requests_dir=message_requests_dir,
            credentials_path=str(creds_path),
            sender_email=sender_email,
            specific_file=specific_file
        )
        
        # Print summary
        logger.info("=" * 60)
        logger.info("Reminder Processing Complete")
        logger.info("=" * 60)
        logger.info(f"Emails sent: {stats['sent']}")
        logger.info(f"Emails skipped: {stats['skipped']}")
        logger.info(f"Errors: {stats['errors']}")
        logger.info("=" * 60)
        
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()

