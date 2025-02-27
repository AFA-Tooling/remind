import sqlite3
from datetime import datetime, timedelta
import argparse

def get_deadlines(db_name, today_date, days_ahead=5):
    """Retrieves deadlines from the database based on today's date and a time window."""
    try:
        conn = sqlite3.connect(db_name)
        cursor = conn.cursor()

        # Overdue deadlines
        cursor.execute("SELECT * FROM deadlines WHERE due < ? AND done = 0", (today_date.isoformat(),))
        overdue = cursor.fetchall()

        # Deadlines within the next 'days_ahead' days
        future_date = today_date + timedelta(days=days_ahead)
        cursor.execute("SELECT * FROM deadlines WHERE due >= ? AND due <= ? AND done = 0", (today_date.isoformat(), future_date.isoformat()))
        upcoming = cursor.fetchall()

        conn.close()
        return overdue, upcoming

    except sqlite3.Error as e:
        print(f"Database error: {e}")
        return [], []

def update_assignment_done(db_name, assignment_id, submission_time):
    """Updates the 'done' status of an assignment to True and sets submission time."""
    try:
        conn = sqlite3.connect(db_name)
        cursor = conn.cursor()
        cursor.execute("UPDATE deadlines SET done = 1, time_submitted = ? WHERE id = ?", (submission_time.isoformat(), assignment_id,))
        conn.commit()
        conn.close()
        print(f"Assignment ID {assignment_id} marked as done at {submission_time}.")
    except sqlite3.Error as e:
        print(f"Database error: {e}")

def reset_all_assignments(db_name):
    """Resets the 'done' status of all assignments to False and clears submission time."""
    try:
        conn = sqlite3.connect(db_name)
        cursor = conn.cursor()
        cursor.execute("UPDATE deadlines SET done = 0, time_submitted = NULL")
        conn.commit()
        conn.close()
        print("All assignments reset to not done.")
    except sqlite3.Error as e:
        print(f"Database error: {e}")

def display_deadlines(overdue, upcoming, today_date):
    """Displays overdue and upcoming deadlines."""
    print("\nOverdue Deadlines:")
    if not overdue:
        print("  None")
    else:
        for row in overdue:
            due_datetime = datetime.fromisoformat(row[2]) # parse as datetime from iso
            due_date = due_datetime.date() # extract date portion
            days_overdue = (today_date - due_date).days
            print(f"  ID: {row[0]}, Project: {row[1]}, Due: {row[2]}, Overdue by: {days_overdue} days")

    print("\nUpcoming Deadlines (within 5 days):")
    if not upcoming:
        print("  None")
    else:
        for row in upcoming:
            print(f"  ID: {row[0]}, Project: {row[1]}, Due: {row[2]}")

def main(db_name="deadlines.db", manual_date=None, manual_time=None, update_id=None, reset=False):
    """Main function to check and display deadlines."""
    if manual_date:
        today_date = datetime.strptime(manual_date, "%Y-%m-%d").date()
    else:
        today_date = datetime.now().date()

    if manual_time:
        today_time = datetime.strptime(manual_time, "%H:%M:%S").time()
        today_datetime = datetime.combine(today_date, today_time)
    else:
        today_datetime = datetime.now().replace(microsecond=0)

    if update_id is not None:
        update_assignment_done(db_name, update_id, today_datetime)
        return

    if reset:
        reset_all_assignments(db_name)
        return

    overdue, upcoming = get_deadlines(db_name, today_date)
    display_deadlines(overdue, upcoming, today_date)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Check and manage CS10 deadlines.")
    parser.add_argument("db_name", nargs='?', default="deadlines.db", help="Path to the SQLite database file.")
    parser.add_argument("--date", help="Manual date (YYYY-MM-DD).")
    parser.add_argument("--time", help="Manual time (HH:MM:SS).")
    parser.add_argument("--update", type=int, help="Update assignment with given ID.")
    parser.add_argument("--reset", action="store_true", help="Reset all assignments to not done.")

    args = parser.parse_args()

    main(args.db_name, args.date, args.time, args.update, args.reset)