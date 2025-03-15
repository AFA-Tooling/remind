import sqlite3
import csv
from datetime import datetime, timedelta
import argparse

def update_csv(db_name, csv_filename="deadlines.csv"):
    """Updates the CSV file with the latest deadlines from the database."""
    try:
        conn = sqlite3.connect(db_name)
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM deadlines")
        rows = cursor.fetchall()
        conn.close()

        # Write to CSV
        with open(csv_filename, "w", newline="") as file:
            writer = csv.writer(file)
            writer.writerow(["id", "project", "due", "done", "time_submitted"])  # Adjust headers if needed
            writer.writerows(rows)
        print(f"CSV file '{csv_filename}' updated.")
    except sqlite3.Error as e:
        print(f"Database error: {e}")

def update_assignment_done(db_name, assignment_id, submission_time):
    """Updates an assignment's 'done' status and updates CSV."""
    try:
        conn = sqlite3.connect(db_name)
        cursor = conn.cursor()
        cursor.execute("UPDATE deadlines SET done = 1, time_submitted = ? WHERE id = ?", (submission_time.isoformat(), assignment_id,))
        conn.commit()
        conn.close()
        print(f"Assignment ID {assignment_id} marked as done at {submission_time}.")
        update_csv(db_name)  # Update CSV after change
    except sqlite3.Error as e:
        print(f"Database error: {e}")

def reset_all_assignments(db_name):
    """Resets all assignments and updates CSV."""
    try:
        conn = sqlite3.connect(db_name)
        cursor = conn.cursor()
        cursor.execute("UPDATE deadlines SET done = 0, time_submitted = NULL")
        conn.commit()
        conn.close()
        print("All assignments reset to not done.")
        update_csv(db_name)  # Update CSV after reset
    except sqlite3.Error as e:
        print(f"Database error: {e}")

def main(db_name="deadlines.db", update_id=None, reset=False):
    """Main function to update deadlines and sync CSV."""
    today_datetime = datetime.now().replace(microsecond=0)

    if update_id is not None:
        update_assignment_done(db_name, update_id, today_datetime)
        return

    if reset:
        reset_all_assignments(db_name)
        return

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Manage deadlines and sync CSV.")
    parser.add_argument("db_name", nargs='?', default="deadlines.db", help="Path to the SQLite database file.")
    parser.add_argument("--update", type=int, help="Update assignment with given ID.")
    parser.add_argument("--reset", action="store_true", help="Reset all assignments to not done.")

    args = parser.parse_args()

    main(args.db_name, args.update, args.reset)
