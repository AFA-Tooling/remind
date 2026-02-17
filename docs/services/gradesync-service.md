# GradeSync Service

The GradeSync Service is the core data processing pipeline. It syncs student grades from Google Sheets to Supabase and generates "message requests" for students who need reminders.

## Workflow

1.  **Ingest (`gradesync_to_db.py`)**:
    *   Reads assignment data from a Google Sheet.
    *   Cleans and standardizes the data.
    *   Upserts the data into the `assignment_submissions` table in Supabase.

2.  **Process (`db_fetch.py`)**:
    *   Reads student data and preferences from Supabase.
    *   Reads assignment deadlines from `shared_data/deadlines.csv`.
    *   Calculates personalized deadlines based on student extensions/offsets.
    *   Determines if a notification is due based on the "days before deadline" preference.
    *   Generates CSV files in `message_requests/` for valid reminders.

## Configuration

Required environment variables in `.env.local`:

```bash
# Supabase
SUPABASE_URL="https://your-project.supabase.co"
SUPABASE_SERVICE_ROLE_KEY="your-service-role-key"

# Google Sheets (for gradesync_to_db.py)
# Uses the same service account as Email Service if configured,
# or a specific one for Sheets.
```

## Usage

### Sync Grades to Database

```bash
python3 services/gradesync_input/gradesync_to_db.py
```

Options:
- `--no-supabase`: Skip upload, just generate CSVs for debugging.
- `--table`: Specify a custom table name.

### Generate Message Requests

```bash
python3 services/gradesync_input/db_fetch.py
```

Options:
- `--mode`: `reminders` (default) or `raw` (inspect data).
- `--debug`: Print detailed decision logic for each student.
- `--discord-csv`: Also generate a CSV for Discord reminders.
- `--gmail-csv`: Also generate CSVs for Gmail reminders.
