import requests
from bs4 import BeautifulSoup
import re
import sqlite3
import os
from datetime import datetime, timedelta

def scrape_cs10_deadlines(url):
    """Scrapes CS10 deadlines from a given URL."""
    try:
        response = requests.get(url)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, "html.parser")
        deadline_texts = []
        pattern = re.compile(r"Due\s*(?:\(\d+/\d+\)|\d+/\d+)|Due\s*Proj")
        for element in soup.find_all(string=pattern):
            parent = element.parent
            while parent is not None and parent.name not in [
                'p', 'li', 'td', 'span', 'a', 'div',
                'h1', 'h2', 'h3', 'h4', 'h5', 'h6'
            ]:
                parent = parent.parent
            if parent is not None and parent.name in [
                'p', 'li', 'td', 'span', 'a', 'div',
                'h1', 'h2', 'h3', 'h4', 'h5', 'h6'
            ]:
                text = parent.get_text(strip=True)
                text = text.replace("Released(Due", "Released Due (")
                text = text.replace("ReleasedDue", "Released Due")
                text = text.replace("DueProj", "Due Proj")
                entries = text.split("Due Proj")
                for i, entry in enumerate(entries):
                    if "Due" in entry and re.search(r"\d+/\d+", entry):
                        if i > 0:
                            entry = "Proj" + entry
                        match = re.search(r"(.*)Due\s*(?:\(\s*(\d+/\d+)\s*\)|\s*(\d+/\d+))", entry)
                        if match:
                            project_name = match.group(1).strip()
                            due_date = match.group(2) or match.group(3)
                            project_name = project_name.replace("Released", "").strip()
                            deadline_texts.append((project_name, due_date))
        return deadline_texts
    except requests.exceptions.RequestException as e:
        print(f"Error fetching URL: {e}")
        return []
    except Exception as e:
        print(f"An error occurred: {e}")
        return []

def init_db(db_name):
    """Initializes the SQLite database if it doesn't exist."""
    conn = sqlite3.connect(db_name)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS deadlines (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project TEXT UNIQUE,
            due TEXT,
            done BOOLEAN DEFAULT 0,
            time_submitted DATETIME
        )
    ''')
    conn.commit()
    return conn

def store_deadlines(conn, deadlines):
    """Stores or updates deadlines in the database, preserving 'done' and 'time_submitted'."""
    cursor = conn.cursor()
    for project_name, due_date in deadlines:
        try:
            due_datetime = datetime.strptime(due_date, "%m/%d").replace(year=2025, hour=23, minute=59, second=59)
            due_datetime_iso = due_datetime.isoformat()

            # Check if the project already exists
            cursor.execute("SELECT done, time_submitted FROM deadlines WHERE project = ?", (project_name,))
            existing_row = cursor.fetchone()

            if existing_row:
                # Update existing row, preserving 'done' and 'time_submitted'
                done_status, time_submitted = existing_row
                cursor.execute("UPDATE deadlines SET due = ? WHERE project = ?", (due_datetime_iso, project_name))
            else:
                # Insert new row
                cursor.execute('INSERT INTO deadlines (project, due, done, time_submitted) VALUES (?, ?, ?, NULL)',
                               (project_name, due_datetime_iso, False))

        except sqlite3.Error as e:
            print(f"Database error: {e}")
            print(f"Trying to insert/update: project='{project_name}', due='{due_date}'")
            conn.rollback()
            raise
        except ValueError as e:
            print(f"Date parsing error: {e}")
            print(f"Problematic date: '{due_date}' for project '{project_name}'")
    conn.commit()

def print_database_contents(db_name):
    """Prints the contents of the database."""
    conn = sqlite3.connect(db_name)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM deadlines")
    rows = cursor.fetchall()
    print("\nDatabase contents:")
    for row in rows:
        print(f"ID: {row[0]}, Project: {row[1]}, Due: {row[2]}, Done: {row[3]}, Time Submitted: {row[4]}")
    conn.close()

if __name__ == "__main__":
    url = "https://cs10.org/sp25/"
    db_name = "deadlines.db"
    deadlines = scrape_cs10_deadlines(url)
    if deadlines:
        print("Deadlines found:")
        for project_name, due_date in deadlines:
            print(f"{project_name}; {due_date}")
        db_connection = init_db(db_name)
        store_deadlines(db_connection, deadlines)
        db_connection.close()
        print(f"Deadlines have been stored/updated in the SQLite database '{db_name}'")
        print_database_contents(db_name)
    else:
        print("No deadlines found on the page.")