# Get the data from the sample_data folder
import os
import pandas as pd
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from supabase import Client, create_client


def load_supabase_env() -> dict:
    """Load Supabase credentials from .env file."""
    # Try loading from current directory first, then project root
    current_dir = Path(__file__).resolve().parent
    env_paths = [
        current_dir / ".env",
        current_dir.parent / ".env",
        current_dir.parent / "remind" / ".env",
    ]
    
    for env_path in env_paths:
        if env_path.exists():
            load_dotenv(env_path)
            break
    else:
        # Fallback to default dotenv behavior
        load_dotenv()

    required_vars = ["SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY"]
    missing = [var for var in required_vars if not os.getenv(var)]

    if missing:
        raise ValueError(
            "Missing required environment variables: " + ", ".join(missing)
        )

    return {
        "url": os.environ["SUPABASE_URL"],
        "service_role_key": os.environ["SUPABASE_SERVICE_ROLE_KEY"],
    }


def load_deadlines_from_supabase() -> pd.DataFrame:
    """
    Load deadlines from Supabase database and return as pandas DataFrame.
    
    Returns:
        DataFrame with columns: assignment_name, due, course_code, assignment_code
        The 'assignment' column is set to assignment_name for compatibility.
    """
    print("📊 Loading deadlines from Supabase...")
    
    try:
        config = load_supabase_env()
        supabase: Client = create_client(config["url"], config["service_role_key"])
        
        # Fetch all deadlines from the database
        response = supabase.table("deadlines").select("*").execute()
        
        if not response.data:
            print("⚠️  No deadlines found in database. Returning empty DataFrame.")
            return pd.DataFrame(columns=["assignment", "due", "course_code", "assignment_code", "assignment_name"])
        
        # Convert to DataFrame
        df = pd.DataFrame(response.data)
        
        # Rename assignment_name to 'assignment' for compatibility with existing code
        if "assignment_name" in df.columns:
            df["assignment"] = df["assignment_name"]
        
        # Convert 'due' to datetime if it's a string
        if "due" in df.columns:
            df["due"] = pd.to_datetime(df["due"], errors="coerce")
        
        print(f"✅ Loaded {len(df)} deadline(s) from Supabase")
        return df
        
    except Exception as e:
        print(f"❌ Error loading deadlines from Supabase: {e}")
        print("⚠️  Falling back to empty DataFrame. Deadlines will not be matched.")
        return pd.DataFrame(columns=["assignment", "due", "course_code", "assignment_code", "assignment_name"])


def load_student_preferences_from_supabase() -> pd.DataFrame:
    """
    Load student preferences (including preferred_first_name) from Supabase.
    
    Returns:
        DataFrame with columns: email, preferred_first_name, and other student fields
    """
    print("📊 Loading student preferences from Supabase...")
    
    try:
        config = load_supabase_env()
        supabase: Client = create_client(config["url"], config["service_role_key"])
        
        # Fetch student preferences from students_duplicate table
        response = supabase.table("students_duplicate").select("email, preferred_first_name").execute()
        
        if not response.data:
            print("⚠️  No student preferences found in database.")
            return pd.DataFrame(columns=["email", "preferred_first_name"])
        
        # Convert to DataFrame
        df = pd.DataFrame(response.data)
        
        print(f"✅ Loaded {len(df)} student preference record(s) from Supabase")
        return df
        
    except Exception as e:
        print(f"⚠️  Warning: Could not load student preferences: {e}")
        print("   Messages will use first name from assignment_submissions instead.")
        return pd.DataFrame(columns=["email", "preferred_first_name"])


def load_assignment_submissions_from_supabase(
    assignment_name: Optional[str] = None
) -> pd.DataFrame:
    """
    Load assignment submissions from Supabase database.
    
    Args:
        assignment_name: Optional assignment name to filter by. If None, loads all assignments.
    
    Returns:
        DataFrame with columns: assignment_name, sid, name, email, status
        The 'assignment' column is set to assignment_name for compatibility.
    """
    print("📊 Loading assignment submissions from Supabase...")
    
    try:
        config = load_supabase_env()
        supabase: Client = create_client(config["url"], config["service_role_key"])
        
        # Build query
        query = supabase.table("assignment_submissions").select("*")
        
        # Filter by assignment_name if provided
        if assignment_name:
            query = query.eq("assignment_name", assignment_name)
        
        # Execute query
        response = query.execute()
        
        if not response.data:
            print("⚠️  No assignment submissions found in database.")
            return pd.DataFrame(columns=["assignment", "sid", "name", "email", "status", "submission time"])
        
        # Convert to DataFrame
        df = pd.DataFrame(response.data)
        
        # Rename assignment_name to 'assignment' for compatibility with existing code
        if "assignment_name" in df.columns:
            df["assignment"] = df["assignment_name"]
        
        # Add 'submission time' column if it doesn't exist (for compatibility)
        # Use updated_at as a proxy if available
        if "submission time" not in df.columns:
            if "updated_at" in df.columns:
                df["submission time"] = df["updated_at"]
            else:
                df["submission time"] = pd.NaT
        
        print(f"✅ Loaded {len(df)} submission record(s) from Supabase")
        if assignment_name:
            print(f"   Filtered by assignment: {assignment_name}")
        else:
            unique_assignments = df["assignment"].nunique() if "assignment" in df.columns else 0
            print(f"   Found {unique_assignments} unique assignment(s)")
        
        return df
        
    except Exception as e:
        print(f"❌ Error loading assignment submissions from Supabase: {e}")
        raise


def process_assignment_from_supabase(
    assignment_name: str,
    deadlines_df: Optional[pd.DataFrame] = None,
    notification_frequency_df=None
):
    """
    Process a single assignment from Supabase and generate message requests.
    
    Args:
        assignment_name: Name of the assignment to process
        deadlines_df: Optional DataFrame with deadlines. If None, loads from Supabase.
        notification_frequency_df: Optional DataFrame with notification frequencies. If None, expects CSV.
    """
    # ------------------------------
    # Step 1: Load Assignment Data from Supabase
    # ------------------------------
    
    print(f"\n📄 Processing assignment: {assignment_name}")
    
    # Load assignment submissions from Supabase
    assignment_df = load_assignment_submissions_from_supabase(assignment_name=assignment_name)
    
    if assignment_df.empty:
        print(f"⚠️  No submissions found for assignment: {assignment_name}")
        return
    
    # Load student preferences (including preferred_first_name) and merge with assignment data
    student_prefs_df = load_student_preferences_from_supabase()
    
    # Merge preferred_first_name into assignment_df based on email
    if not student_prefs_df.empty and 'email' in assignment_df.columns:
        # Merge on email, keeping all assignment_submissions rows
        assignment_df = assignment_df.merge(
            student_prefs_df[['email', 'preferred_first_name']],
            on='email',
            how='left'
        )
        print(f"✅ Merged student preferences (preferred_first_name) with assignment data")
    else:
        # Add empty preferred_first_name column if merge not possible
        assignment_df['preferred_first_name'] = None
        print("⚠️  Could not merge student preferences. Using names from assignment_submissions.")
    
    # Print the first 5 rows of the dataframe
    print(f"\n📊 Assignment Data Preview:")
    print(assignment_df.head())


    # ------------------------------
    # Step 2: Integrate with Deadlines
    # ------------------------------

    # Load deadlines from Supabase if not provided
    if deadlines_df is None:
        deadlines_df = load_deadlines_from_supabase()
    
    # Ensure deadlines_df has the expected structure
    if deadlines_df.empty:
        print("⚠️  Warning: No deadlines available. All due dates will be set to NaT.")
    elif "assignment" not in deadlines_df.columns and "assignment_name" in deadlines_df.columns:
        deadlines_df["assignment"] = deadlines_df["assignment_name"]

    # Iterate through the assignment_filtered_df, and for each row, add on the due date based on joining the project3_filtered_df and the deadlines_df
    def get_due_date(row):
        # Get the project name from the row
        project_name = row['assignment']
    
        # Get the due date from the deadlines_df
        if deadlines_df.empty or project_name not in deadlines_df['assignment'].values:
            due_date = pd.NaT
        else:
            due_date = deadlines_df.loc[deadlines_df['assignment'] == project_name, 'due'].values[0]
        return due_date

    assignment_df['due date'] = assignment_df.apply(get_due_date, axis=1)
    print("\n📅 After adding due dates:")
    print(assignment_df.head())

    # Convert the due date and submission time to datetime objects, in order to compare the dates for the date difference
    assignment_df['submission time'] = pd.to_datetime(assignment_df['submission time'], errors='coerce', utc=True)
    assignment_df['due date'] = pd.to_datetime(assignment_df['due date'], errors='coerce')
    print("\n🕐 After converting to datetime:")
    print(assignment_df.head())


    # ------------------------------
    # Step 3: Integrate with Notification Frequency
    # ------------------------------

    # Match the first and last name column from the assignment_filtered_df with the first name and last name column from the notification_frequency_df 
    def get_notification_frequency(row):
        student_name = row['name']
        
        # If notification_frequency_df is not provided, use default
        if notification_frequency_df is None or notification_frequency_df.empty:
            return 3  # Default: 3 days before the due date
        
        # Correct structure: [ROW CONDITION, COLUMN NAME]
        match = notification_frequency_df.loc[
            (notification_frequency_df['name'] == student_name), 
            'notification_frequency' 
        ]

        # If there is a match, return the notification frequency
        if not match.empty:
            return match.values[0]
        else:
            # Make the default reminder frequency = 3 days before the due date
            return 3

    assignment_df['notification_frequency'] = assignment_df.apply(get_notification_frequency, axis=1)
    print("\n🔔 Merged DataFrame with Notification Frequency:")
    print(assignment_df.head())

    # Convert the notification_frequency column in assignment_filtered_df to a timedelta object
    assignment_df['notification_frequency'] = assignment_df['notification_frequency'].apply(lambda x: pd.Timedelta(days=x))
    print("\n⏱️  Converted notification_frequency to timedelta:")
    print(assignment_df.head())


    # ------------------------------
    # Step 4: Date Comparison Logic
    # ------------------------------

    # Get the difference between the due date and the current date
    TODAY_DATE = pd.to_datetime(datetime.now()).normalize()
    assignment_df['date_diff'] = assignment_df['due date'] - TODAY_DATE
    
    assignment_df.head()

    notification_days = pd.to_timedelta(assignment_df['notification_frequency']).dt.days
    date_diff_days = pd.to_timedelta(assignment_df['date_diff']).dt.days
    
    assignment_df['is_equal'] = notification_days == date_diff_days
    print("\n✅ Successfully compared the notification frequency and the difference with today's date:")
    print(assignment_df.head())

    # ------------------------------
    # Step 5: Create Missing Students DataFrame
    # ------------------------------
    """
    What will the code do:			
    1. Iterate through every single row in this table			
    2. Student SID has not submitted assignment, status = 'missing' from student_data_one_assignment AND today_date == due_date - notification_freq			
    3. Append that student, row, assignment to the message_requests temporary dataframe			
    4. Continue iterating through every single one			
    """

    # See which rows where row['status'] == 'Missing' (case-insensitive) and row['is_equal'] == True:
    # Handle case-insensitive status matching
    assignment_df['status_lower'] = assignment_df['status'].astype(str).str.lower()
    missing_students_df = assignment_df[
        (assignment_df['status_lower'] == 'missing') & 
        (assignment_df['is_equal'] == True)
    ].copy()
    # Drop the temporary status_lower column
    if 'status_lower' in missing_students_df.columns:
        missing_students_df = missing_students_df.drop(columns=['status_lower'])
    
    print(f"\n📋 Found {len(missing_students_df)} student(s) needing reminders")
    if not missing_students_df.empty:
        print(missing_students_df.head())

    # Now create a message_requests column in the merged_df dataframe with the f_string message
    def create_message(row):
        # Get the assignment name from the row
        assignment_name = row['assignment']

        # Get notification frequency in days (extract days from timedelta)
        notification_frequency_days = int(pd.to_timedelta(row['notification_frequency']).days)

        # Get preferred first name if available, otherwise use first name from name field
        preferred_first_name = row.get('preferred_first_name')
        student_name = row.get("name", "")
        
        # Priority: preferred_first_name > first word of name > "there"
        if preferred_first_name and pd.notna(preferred_first_name) and str(preferred_first_name).strip():
            first_name = str(preferred_first_name).strip()
        elif student_name and pd.notna(student_name) and str(student_name).strip():
            # Use first name if full name is provided
            first_name = str(student_name).split()[0] if student_name else "there"
        else:
            first_name = "there"

        # Create the message
        message = f"Dear {first_name}, your {assignment_name} assignment is missing and it is due in {notification_frequency_days} days. Please submit it as soon as possible."

        return message

    # Create the message_requests column in the merged_df dataframe
    message_requests_df = missing_students_df.copy()
    message_requests_df['message_requests'] = message_requests_df.apply(create_message, axis=1)
    print("\n💬 Message Requests DataFrame:")
    print(message_requests_df.head())


    # ------------------------------
    # Step 6: Export missing students to csv
    # ------------------------------

    # Simplify this down to the information that is necessary
    # Ensure all required columns exist
    required_columns = ['name', 'sid', 'email', 'assignment', 'message_requests']
    available_columns = [col for col in required_columns if col in message_requests_df.columns]
    
    if len(available_columns) < len(required_columns):
        missing = set(required_columns) - set(available_columns)
        print(f"⚠️  Warning: Missing columns {missing}. Available columns: {list(message_requests_df.columns)}")
    
    message_requests_df_condensed = message_requests_df[available_columns]
    print("\n📦 Condensed Message Requests DataFrame:")
    print(message_requests_df_condensed.head())

    if message_requests_df_condensed.empty:
        print("ℹ️  No students matched the notification criteria. Skipping CSV generation.")
        return 

    def _safe_filename_basic(name: str) -> str:
       """
       Return a Windows-safe filename by replacing ':' and runs of '*' with ' - ', etc
       """
       cleaned = name.replace(":", " - ")
       cleaned = re.sub(r'\*+', ' - ', cleaned)
       cleaned = re.sub(r'\s+', ' ', cleaned).strip().rstrip(' .')
       return cleaned
    
    raw_assignment_title = message_requests_df_condensed['assignment'].iloc[0]
    safe_assignment_title = _safe_filename_basic(raw_assignment_title)

    # Save the message requests to a CSV file
    csv_file_name = f"message_requests_{safe_assignment_title}.csv"
    print(f"\n💾 Saving message requests to {csv_file_name}")

    # Save the dataframe to the message_requests/ folder
    message_requests_folder = 'message_requests/'
    if not os.path.exists(message_requests_folder):
        os.makedirs(message_requests_folder)
    
    output_path = os.path.join(message_requests_folder, csv_file_name)
    message_requests_df_condensed.to_csv(output_path, index=False)
    print(f"✅ Message requests saved to {output_path}")


def process_all_assignments_from_supabase(
    deadlines_df: Optional[pd.DataFrame] = None,
    notification_frequency_df=None,
    assignment_filter: Optional[str] = None
):
    """
    Process all assignments from Supabase and generate message requests.
    
    Args:
        deadlines_df: Optional DataFrame with deadlines. If None, loads from Supabase.
        notification_frequency_df: Optional DataFrame with notification frequencies.
        assignment_filter: Optional string to filter assignments (e.g., "Project" to only process projects).
    """
    print("=" * 60)
    print("Processing All Assignments from Supabase")
    print("=" * 60)
    
    # Load all assignment submissions
    all_submissions_df = load_assignment_submissions_from_supabase()
    
    if all_submissions_df.empty:
        print("⚠️  No assignment submissions found in database.")
        return
    
    # Get unique assignment names
    unique_assignments = all_submissions_df['assignment'].unique() if 'assignment' in all_submissions_df.columns else []
    
    if not len(unique_assignments):
        print("⚠️  No assignments found.")
        return
    
    # Filter assignments if filter is provided
    if assignment_filter:
        unique_assignments = [a for a in unique_assignments if str(a).startswith(assignment_filter)]
        print(f"🔍 Filtering to assignments starting with '{assignment_filter}': {len(unique_assignments)} found")
    
    print(f"\n📚 Found {len(unique_assignments)} unique assignment(s) to process")
    
    # Process each assignment
    for assignment_name in unique_assignments:
        try:
            process_assignment_from_supabase(
                assignment_name=assignment_name,
                deadlines_df=deadlines_df,
                notification_frequency_df=notification_frequency_df
            )
        except Exception as e:
            print(f"❌ Error processing {assignment_name}: {e}")
            continue
    
    print("\n" + "=" * 60)
    print("✅ All assignments processed!")
    print("=" * 60)


# Backward compatibility: Keep the old function name but redirect to new implementation
def process_assignment_file(assignment_name_or_file: str, deadlines_df: Optional[pd.DataFrame] = None, notification_frequency_df=None):
    """
    Backward compatibility wrapper.
    
    If assignment_name_or_file looks like a file path (contains '/' or ends with '.csv'),
    it will try to load from CSV. Otherwise, it treats it as an assignment name from Supabase.
    """
    # Check if it looks like a file path
    if '/' in assignment_name_or_file or assignment_name_or_file.endswith('.csv'):
        print("⚠️  File-based processing is deprecated. Please use Supabase instead.")
        print(f"   Attempting to process as assignment name: {assignment_name_or_file}")
        # Extract assignment name from file name if possible
        assignment_name = assignment_name_or_file.replace('.csv', '').replace('output/', '')
    else:
        assignment_name = assignment_name_or_file
    
    # Process from Supabase
    process_assignment_from_supabase(
        assignment_name=assignment_name,
        deadlines_df=deadlines_df,
        notification_frequency_df=notification_frequency_df
    )


def main():
    """
    Main entry point for processing assignments from Supabase.
    
    Usage examples:
        # Process all assignments
        python df_to_message_requests.py
        
        # Process only assignments starting with "Project"
        python df_to_message_requests.py --filter "Project"
        
        # Process a specific assignment
        python df_to_message_requests.py --assignment "Project 3: 2048"
    """
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Generate message requests from Supabase assignment submissions"
    )
    parser.add_argument(
        "--assignment",
        "-a",
        type=str,
        help="Process a specific assignment by name"
    )
    parser.add_argument(
        "--filter",
        "-f",
        type=str,
        help="Filter assignments by prefix (e.g., 'Project' to only process projects)"
    )
    parser.add_argument(
        "--notification-csv",
        "-n",
        type=str,
        help="Path to notification frequency CSV file (optional)"
    )
    
    args = parser.parse_args()
    
    # Load notification frequency CSV if provided
    notification_frequency_df = None
    if args.notification_csv:
        try:
            notification_frequency_df = pd.read_csv(args.notification_csv)
            print(f"✅ Loaded notification frequencies from {args.notification_csv}")
        except Exception as e:
            print(f"⚠️  Warning: Could not load notification frequency CSV: {e}")
            print("   Using default notification frequency (3 days)")
    else:
        # Try default location
        default_path = Path(__file__).parent / "shared_data" / "notification_frequency.csv"
        if default_path.exists():
            try:
                notification_frequency_df = pd.read_csv(default_path)
                print(f"✅ Loaded notification frequencies from default location: {default_path}")
            except Exception as e:
                print(f"⚠️  Warning: Could not load default notification frequency CSV: {e}")
                print("   Using default notification frequency (3 days)")
    
    # Process based on arguments
    if args.assignment:
        # Process a specific assignment
        process_assignment_from_supabase(
            assignment_name=args.assignment,
            deadlines_df=None,  # Will load from Supabase
            notification_frequency_df=notification_frequency_df
        )
    else:
        # Process all assignments (with optional filter)
        process_all_assignments_from_supabase(
            deadlines_df=None,  # Will load from Supabase
            notification_frequency_df=notification_frequency_df,
            assignment_filter=args.filter
        )


if __name__ == "__main__":
    main()