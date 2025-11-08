# Gmail Reminder Service for AutoRemind

This service sends automated Gmail reminders to students about pending assignments using the Gmail API and Supabase.

## Features

- Connects to Supabase to fetch student data
- Filters students based on reminder preferences (`in_autoremind`, `notify_gmail`, `submitted`)
- Respects notification frequency (`notification_freq_days`)
- Sends friendly, personalized reminder emails via Gmail API
- Updates `last_reminder_sent` timestamp after successful sends
- Comprehensive logging of all operations

## Setup

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure Environment Variables

Create a `.env` file or set the following environment variables:

```bash
# Supabase Configuration
export SUPABASE_URL="https://your-project.supabase.co"
export SUPABASE_KEY="your-supabase-anon-key"

# Gmail Configuration (optional, defaults provided)
export GMAIL_CREDENTIALS_PATH="config/credentials.json"
export GMAIL_SENDER_EMAIL="autoremind@yourdomain.com"

# Supabase Table Name (optional, defaults to "autoremind_users")
export SUPABASE_TABLE="autoremind_users"
```

### 3. Google Cloud Service Account Setup

1. Create a Google Cloud Project (if you don't have one)
2. Enable the Gmail API
3. Create a Service Account
4. Download the service account credentials JSON file
5. Place it in `config/credentials.json` (or set `GMAIL_CREDENTIALS_PATH`)

**Important**: The service account must be authorized to send emails from `autoremind@yourdomain.com`:
- In Google Workspace Admin, enable domain-wide delegation for the service account
- Grant the service account permission to send emails on behalf of the sender email

### 4. Supabase Table Structure

Your Supabase table should have the following columns (at minimum):

- `student_id` (text/string): Unique student identifier
- `email` (text/string): Student email address
- `in_autoremind` (boolean): Whether student is enrolled in AutoRemind
- `notify_gmail` (boolean): Whether to send Gmail reminders
- `submitted` (boolean): Whether assignment is submitted
- `last_reminder_sent` (timestamp): Last time a reminder was sent (nullable)
- `notification_freq_days` (integer): Days between reminders
- `assignment_name` (text/string): Name of the assignment
- `assignment_id` (text/string, optional): Assignment identifier (if using composite keys)
- `resources` or `resource_links` (text/array, optional): Resource links for the assignment

## Usage

### Run the Service

```bash
python main.py
```

The service will:
1. Connect to Supabase
2. Fetch all students from the specified table
3. Filter students based on criteria
4. Send reminders to eligible students
5. Update `last_reminder_sent` timestamps
6. Log all operations to `gmail_reminder.log` and console

### Example Output

```
2024-01-15 10:00:00 - INFO - Starting Gmail Reminder Service for AutoRemind
2024-01-15 10:00:01 - INFO - Connected to Supabase
2024-01-15 10:00:02 - INFO - Found 150 students in database
2024-01-15 10:00:05 - INFO - ✓ Sent reminder to student@example.com for Project 1
...
2024-01-15 10:00:30 - INFO - Emails sent: 25
2024-01-15 10:00:30 - INFO - Emails skipped: 120
2024-01-15 10:00:30 - INFO - Errors: 5
```

## File Structure

```
gmail-reminder-service/
├── main.py                 # Main orchestration script
├── gmail_service.py        # Gmail API functions
├── supabase_client.py      # Supabase client initialization
├── requirements.txt        # Python dependencies
├── README.md              # This file
└── config/
    └── credentials.json   # Google service account credentials (not in repo)
```

## Functions

### `should_send_reminder(last_sent, freq_days)`
Checks if enough days have passed since the last reminder.

### `format_resources(resources)`
Formats a list of resource links into a bulleted string.

### `send_gmail_reminder(student, assignment_name, resources, ...)`
Sends a Gmail reminder to a student.

### `update_last_sent(supabase, student_id, assignment_id)`
Updates the `last_reminder_sent` timestamp in Supabase.

## Email Format

**Subject**: `Reminder: [assignment_name] is due soon!`

**Body**:
```
Hi [student_id],

You still have "[assignment_name]" pending. Here are some resources that might help:
- [link1]
- [link2]

You've got this! 💪

– The AutoRemind Team
```

## Error Handling

The service handles errors gracefully:
- Missing credentials → Logs error and exits
- Gmail API errors → Logs error and continues with next student
- Supabase errors → Logs error and continues
- All errors are logged to both file and console

## Logging

Logs are written to:
- `gmail_reminder.log` (file)
- Console/stdout

Log levels:
- `INFO`: Normal operations, successful sends
- `WARNING`: Non-fatal issues (e.g., missing email)
- `ERROR`: Failed operations
- `DEBUG`: Detailed filtering decisions (if enabled)

## Scheduling

To run this service automatically, you can:

1. **Cron** (Linux/Mac):
   ```bash
   # Run daily at 9 AM
   0 9 * * * cd /path/to/gmail-reminder-service && python main.py
   ```

2. **Systemd Timer** (Linux)

3. **Cloud Scheduler** (GCP/AWS)

4. **GitHub Actions** (with scheduled workflows)

## Troubleshooting

### "Missing Supabase credentials"
- Ensure `SUPABASE_URL` and `SUPABASE_KEY` are set

### "Credentials file not found"
- Check that `config/credentials.json` exists
- Or set `GMAIL_CREDENTIALS_PATH` environment variable

### "Failed to send email"
- Verify service account has Gmail API enabled
- Check domain-wide delegation is configured
- Ensure sender email is authorized for service account

### "Failed to update last_reminder_sent"
- Check Supabase table permissions
- Verify `student_id` and `assignment_id` columns exist
- Check network connectivity to Supabase

## License

Part of the AutoRemind project.

