import csv
import os
from datetime import datetime, timedelta
import argparse

def read_csv(csv_filename):
    """Reads data from a CSV file."""
    data = []
    if os.path.exists(csv_filename):
        with open(csv_filename, 'r', newline='') as file:
            reader = csv.reader(file)
            headers = next(reader)  # Get headers
            for row in reader:
                data.append(row)
    else:
        print(f"CSV file '{csv_filename}' not found.")
    return data

def write_csv(csv_filename, headers, data):
    """Writes data to a CSV file."""
    with open(csv_filename, 'w', newline='') as file:
        writer = csv.writer(file)
        writer.writerow(headers)
        writer.writerows(data)
    print(f"CSV file '{csv_filename}' updated.")

def update_assignment_done(csv_filename, assignment_id, submission_time):
    """Updates an assignment's 'done' status in the CSV file."""
    try:
        data = read_csv(csv_filename)
        if not data:
            print(f"No data found in {csv_filename}")
            return
            
        # Assuming CSV structure: id, project, due, done, time_submitted
        updated = False
        for row in data:
            if row[0] == str(assignment_id):  # Convert ID to string for comparison
                row[3] = '1'  # Mark as done
                row[4] = submission_time.isoformat()  # Update submission time
                updated = True
                break
                
        if updated:
            write_csv(csv_filename, ["id", "project", "due", "done", "time_submitted"], data)
            print(f"Assignment ID {assignment_id} marked as done at {submission_time}.")
        else:
            print(f"Assignment ID {assignment_id} not found in the CSV.")
    except Exception as e:
        print(f"Error updating CSV: {e}")

def reset_all_assignments(csv_filename):
    """Resets all assignments to not done in the CSV file."""
    try:
        data = read_csv(csv_filename)
        if not data:
            print(f"No data found in {csv_filename}")
            return
            
        # Reset 'done' status and submission time
        for row in data:
            row[3] = '0'  # Set done to False
            row[4] = ''   # Clear submission time
            
        write_csv(csv_filename, ["id", "project", "due", "done", "time_submitted"], data)
        print("All assignments reset to not done.")
    except Exception as e:
        print(f"Error resetting CSV: {e}")

def main(csv_filename="deadlines.csv", update_id=None, reset=False):
    """Main function to update deadlines in CSV."""
    today_datetime = datetime.now().replace(microsecond=0)

    if update_id is not None:
        update_assignment_done(csv_filename, update_id, today_datetime)
        return

    if reset:
        reset_all_assignments(csv_filename)
        return

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Manage deadlines in CSV format.")
    parser.add_argument("csv_filename", nargs='?', default="deadlines.csv", help="Path to the CSV file.")
    parser.add_argument("--update", type=int, help="Update assignment with given ID.")
    parser.add_argument("--reset", action="store_true", help="Reset all assignments to not done.")

    args = parser.parse_args()

    main(args.csv_filename, args.update, args.reset)