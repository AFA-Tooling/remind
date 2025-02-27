import sqlite3

def print_database_contents(db_name):
    """Prints all columns and rows of the database."""
    try:
        conn = sqlite3.connect(db_name)
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM deadlines")
        rows = cursor.fetchall()

        if not rows:
            print("\nDatabase is empty.")
            return

        # Get column names
        column_names = [description[0] for description in cursor.description]

        print("\nDatabase contents:")
        print(", ".join(column_names))  # Print column headers

        for row in rows:
            row_values = ", ".join(str(value) for value in row)
            print(row_values)

        conn.close()

    except sqlite3.Error as e:
        print(f"Database error: {e}")
    except FileNotFoundError:
        print(f"Database file '{db_name}' not found.")

if __name__ == "__main__":
    db_name = "deadlines.db"
    print_database_contents(db_name)