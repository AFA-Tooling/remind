# gradesync_input

This folder contains the core input-processing logic for AutoRemind's automated notification system. It includes scripts to extract, parse, and transform grade-related data from a Google Sheet into formatted message requests.

## Files

### `gradesync_to_df.py`
- **Purpose**: Uses Google Sheet API to parse through the given spreadsheet and upload assignment submission data to Supabase database.
- **Functionality**:
  - Authenticates with the Google Sheets API, fetches all assignment tabs from a specific sheet, and skips summary tabs (e.g., 'Roster', 'Labs') to isolate raw assignment submissions.
  - Extracts essential columns (Name, SID, Email, Status, Submission Time, Lateness), pads shorter rows, adds an Assignment identifier, and standardizes all column headers for downstream processing
  - Uploads cleaned data to Supabase `assignment_submissions` table using upsert logic (updates existing records, inserts new ones)
  - Converts lateness from "H:M:S" format to total seconds for database storage
  - Optionally exports CSV files for debugging with `--csv-fallback` flag
- **Usage**: 
  ```bash
  # Default: Upload to Supabase (requires .env with Supabase credentials)
  python gradesync_to_df.py
  
  # Disable Supabase, write CSV files only
  python gradesync_to_df.py --no-supabase
  
  # Upload to Supabase AND write CSV files for debugging
  python gradesync_to_df.py --csv-fallback
  
  # Custom table name and course code
  python gradesync_to_df.py --table my_submissions --course-code CS61A
  ```
- **Environment Variables** (required for Supabase upload):
  - `SUPABASE_URL`: Your Supabase project URL
  - `SUPABASE_SERVICE_ROLE_KEY`: Your Supabase service role key (stored in `.env` file)
- **Database Schema**: See `assignment_submissions_schema.sql` for the required table structure

### `df_to_message_requests.py`
- **Purpose**: Converts the output DataFrame into message request files if necessary.
- **Functionality**:
  - Filters the DataFrame for tabs relevant to notifications (e.g., Labs and Projects).
  - Checks each assignment's due date against the current date and the configured notification frequency.
  - Generates corresponding message request files in the `message_requests` folder.
- **Usage**: Should be run regularly (e.g., daily via cron) to generate timely reminders.

### `main.py`
- **Purpose**: Orchestrates the full workflow by importing and executing both modules in sequence.

### `deadlines.csv`
- **Purpose**: Lists all deadlines and due dates for a particular class; to be used against comparing student's notification preferences and their assigment submission status.

### `notification_frequency.csv`
- **Purpose**: List of student names, relavent information (such as SID/email), and their notification frequency. This file was handwritten for now, but actual information will be stored in a DB to be accessed.

### `db_fetch.py`
- **Purpose**: Connects to Supabase using `.env` credentials, loads student/course data, and drafts reminder messages for each opt-in student based on personalized deadlines and notification frequencies.
- **Usage**:
  ```bash
  # Run the reminder pipeline (default mode)
  python db_fetch.py --mode reminders

  # Inspect raw Supabase tables
  python db_fetch.py --mode raw --table assignment_resources --limit 5

  # Enable verbose debugging to trace deadline decisions
  python db_fetch.py --mode reminders --debug --limit 2
  ```
- **Inputs**:
  - `.env` with `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY`.
  - `shared_data/deadlines.csv` containing `course_code`, `assignment_code`, and `assignment_name` with due timestamps.
  - Supabase tables:
    - `students` – opt-in flags, `notif_freq_days`, contact preferences, and assignment offset columns (`PROJ01`, `PROJ02`, ...).
    - `assignment_resources` – per-course assignment metadata plus helpful resource links.
- **Output**: Prints each student ready for reminders, their delivery channels, the assignments that triggered (with personalized deadlines/resources), and the draft message text ready for downstream services.


## How to Run

### Setup
1. Create a `.env` file in the `gradesync_input` directory with:
   ```
   SUPABASE_URL=https://your-project.supabase.co
   SUPABASE_SERVICE_ROLE_KEY=your-service-role-key
   ```

2. Run the SQL schema in your Supabase SQL editor (see `assignment_submissions_schema.sql`)

### Running the Scripts
1. Open a terminal and navigate to this folder:
   ```bash
   cd gradesync_input
   ```

2. Parse through the google sheet and upload to Supabase:
   ```bash
   python gradesync_to_df.py
   ```

3. Run the main pipeline to generate message requests:
   ```bash
   python main.py
   ```
## Dependencies
- `pandas` - Data manipulation
- `numpy` - Numerical operations
- `python-dotenv` - Environment variable management
- `supabase` - Supabase Python client
- Google Sheets API client libraries (`google-api-python-client`, `google-auth`, etc.)
- `psycopg2-binary` - PostgreSQL adapter (for direct database access if needed)

## Current Setup
The script is currently configured to read from a test sheet deployed by GradeSync. Ensure the correct credentials and sheet ID are used before deploying.

## Output
- Message request files are created and stored in the `message_requests` directory.
- These are consumed by downstream services for sending reminders via email or messaging platforms.

## Notes
- Only assignments in specific tabs (Labs and Projects) are currently processed for notifications.
- Ensure that due dates and notification settings are formatted correctly in the sheet.

---

Maintained by the AutoRemind development team.
