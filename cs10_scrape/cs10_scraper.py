import requests
from bs4 import BeautifulSoup
import re
import sqlite3

def scrape_cs10_deadlines(url):
    try:
        response = requests.get(url)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, "html.parser")
        deadline_texts = []
        # Improved regex: looks for "Due" followed by a date OR "Due" followed by "Proj"
        pattern = re.compile(r"Due\s*(?:\(\d+/\d+\)|\d+/\d+)|Due\s*Proj")

        for element in soup.find_all(text=pattern):
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

                # Normalize and split entries:
                text = text.replace("Released(Due", "Released Due (")
                text = text.replace("ReleasedDue", "Released Due")
                text = text.replace("DueProj", "Due Proj")

                # Split on "Due Proj" BUT preserve "Proj" for later entries
                entries = text.split("Due Proj")
                for i, entry in enumerate(entries):  # Use enumerate to get the index
                    if "Due" in entry and re.search(r"\d+/\d+", entry):
                        if i > 0:  # If it's not the first entry (i.e. after a split)
                            entry = "Proj" + entry # Add "Proj" back in
                        deadline_texts.append(entry.strip())

        return deadline_texts

    except requests.exceptions.RequestException as e:
        print(f"Error fetching URL: {e}")
        return []
    except Exception as e:
        print(f"An error occurred: {e}")
        return []

def init_db(db_name):
    """
    Initializes a SQLite database with a table for deadlines.

    Args:
        db_name: The name of the SQLite database file.

    Returns:
        A SQLite connection object.
    """
    conn = sqlite3.connect(db_name)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS deadlines (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            deadline_text TEXT
        )
    ''')
    conn.commit()
    return conn

def store_deadlines(conn, deadlines):
    """
    Stores deadline texts into the SQLite database.

    Args:
        conn: SQLite connection object.
        deadlines: A list of deadline text strings.
    """
    cursor = conn.cursor()
    for deadline in deadlines:
        cursor.execute('INSERT INTO deadlines (deadline_text) VALUES (?)', (deadline,))
    conn.commit()

if __name__ == "__main__":
    url = "https://cs10.org/sp25/"  # The CS 10 Spring 2025 course page
    deadlines = scrape_cs10_deadlines(url)
    if deadlines:
        print("Deadlines found:")
        for deadline in deadlines:
            print(deadline)
        # Initialize the database and store deadlines
        db_connection = init_db("deadlines.db")
        store_deadlines(db_connection, deadlines)
        db_connection.close()
        print("Deadlines have been stored in the SQLite database 'deadlines.db'")
    else:
        print("No deadlines found on the page.")