# gradesync_input

This folder contains the core input-processing logic for AutoRemind's automated notification system. It includes scripts to extract, parse, and transform grade-related data from a Google Sheet into formatted message requests.

## Files

### `gradesync_to_df.py`
- **Purpose**: Uses Google Sheet API to parse through the given spreadsheet and obain necessary information required for AutoRemind.
- **Functionality**:
  - Authenticates with the Google Sheets API, fetches all assignment tabs from a specific sheet, and skips summary tabs (e.g., 'Roster', 'Labs') to isolate raw assignment submissions.
  - Extracts essential columns (Name, SID, Email, Status, Submission Time, Lateness), pads shorter rows, adds an Assignment identifier, and standardizes all column headers for downstream processing
  - Iterates through each processed assignment tab and exports the cleaned data as a separate, Windows-safe CSV file into a local output/ directory
- **Usage**: Should be run regularly (e.g., daily via cron) to grab updated student information.

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


## How to Run
1. Open a terminal and navigate to this folder:
   ```bash
   cd gradesync_input
2. Parse through the google sheet and create the DataFrame:
    ```bash
    python gradesync_to_df
3. Run the main pipeline to generate message requests:
    ```bash
    python main.py
## Dependencies
- `pandas`
- `datetime`
- Google Sheets API client libraries
- Your internal messaging/email services (e.g., Twilio, SendGrid)

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
