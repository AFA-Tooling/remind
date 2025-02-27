import requests
from bs4 import BeautifulSoup
import re
import sqlite3
import os

def scrape_cs10_deadlines(url):
    try:
        response = requests.get(url)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, "html.parser")
        deadline_texts = []
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

                            # Remove "Released" from project name
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
    # Delete the database file if it exists
    if os.path.exists(db_name):
        os.remove(db_name)

    conn = sqlite3.connect(db_name)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS deadlines (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project TEXT,
            due TEXT
        )
    ''')
    conn.commit()
    return conn

def store_deadlines(conn, deadlines):
    cursor = conn.cursor()
    for project_name, due_date in deadlines:
        try:
            cursor.execute('INSERT INTO deadlines (project, due) VALUES (?, ?)', (project_name, due_date))
        except sqlite3.Error as e:
            print(f"Database error: {e}")
            print(f"Trying to insert: project='{project_name}', due='{due_date}'")
            conn.rollback()
            raise

    conn.commit()


if __name__ == "__main__":
    url = "https://cs10.org/sp25/"
    deadlines = scrape_cs10_deadlines(url)
    if deadlines:
        print("Deadlines found:")
        for project_name, due_date in deadlines:
            print(f"{project_name}; {due_date}")

        db_connection = init_db("deadlines.db")
        store_deadlines(db_connection, deadlines)
        db_connection.close()
        print("Deadlines have been stored in the SQLite database 'deadlines.db'")
    else:
        print("No deadlines found on the page.")