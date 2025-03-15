import sqlite3
import csv

def export_database_to_csv(db_name, csv_filename):
    """Exports all columns and rows from the database to a CSV file."""
    try:
        conn = sqlite3.connect(db_name)
        cursor = conn.cursor()

        # Fetch all rows from the 'deadlines' table
        cursor.execute("SELECT * FROM deadlines")
        rows = cursor.fetchall()

        if not rows:
            print("\nDatabase is empty. No data to export.")
            return

        # Get column names
        column_names = [description[0] for description in cursor.description]

        # Write to CSV
        with open(csv_filename, mode="w", newline="") as csv_file:
            writer = csv.writer(csv_file)
            writer.writerow(column_names)  # Write headers
            writer.writerows(rows)  # Write data rows

        print(f"\nDatabase successfully exported to '{csv_filename}'.")

        conn.close()

    except sqlite3.Error as e:
        print(f"Database error: {e}")
    except FileNotFoundError:
        print(f"Database file '{db_name}' not found.")

if __name__ == "__main__":
    db_name = "deadlines.db"
    csv_filename = "deadlines.csv"
    export_database_to_csv(db_name, csv_filename)
