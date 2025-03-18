import csv
import os
from datetime import datetime
import argparse

def read_csv(csv_filename):
    """Reads data from a CSV file."""
    data = []
    headers = []
    if os.path.exists(csv_filename):
        with open(csv_filename, 'r', newline='') as file:
            reader = csv.reader(file)
            try:
                headers = next(reader)  # Get headers
                for row in reader:
                    data.append(row)
            except StopIteration:
                print(f"CSV file '{csv_filename}' is empty or improperly formatted.")
    else:
        print(f"CSV file '{csv_filename}' not found.")
    return headers, data

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
        headers, data = read_csv(csv_filename)
        if not data:
            print(f"No data found in {csv_filename}")
            return
        
        # Find the correct column indices
        id_col = headers.index("id") if "id" in headers else 0
        done_col = headers.index("done") if "done" in headers else 3
        time_col = headers.index("time_submitted") if "time_submitted" in headers else 4
        
        assignment_id_str = str(assignment_id)
        updated = False
        
        for row in data:
            if len(row) > id_col and row[id_col] == assignment_id_str:
                # Ensure row has enough elements
                while len(row) <= max(done_col, time_col):
                    row.append("")
                    
                row[done_col] = '1'  # Mark as done
                row[time_col] = submission_time.isoformat()  # Update submission time
                updated = True
                break
                
        if updated:
            write_csv(csv_filename, headers, data)
            print(f"Assignment ID {assignment_id} marked as done at {submission_time}.")
        else:
            print(f"Assignment ID {assignment_id} not found in the CSV.")
    except Exception as e:
        print(f"Error updating CSV: {e}")

def reset_all_assignments(csv_filename):
    """Resets all assignments to not done in the CSV file."""
    try:
        headers, data = read_csv(csv_filename)
        if not data:
            print(f"No data found in {csv_filename}")
            return
            
        # Find the correct column indices
        done_col = headers.index("done") if "done" in headers else 3
        time_col = headers.index("time_submitted") if "time_submitted" in headers else 4
            
        # Reset 'done' status and submission time
        for row in data:
            # Ensure row has enough elements before trying to modify them
            while len(row) <= max(done_col, time_col):
                row.append("")
                
            row[done_col] = '0'  # Set done to False
            row[time_col] = ''   # Clear submission time
            
        write_csv(csv_filename, headers, data)
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