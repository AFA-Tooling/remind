import requests
from bs4 import BeautifulSoup
import re
import csv
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

def read_existing_csv(csv_filename):
    """Reads existing data from CSV file if it exists."""
    existing_data = {}
    if os.path.exists(csv_filename):
        with open(csv_filename, 'r', newline='') as csvfile:
            reader = csv.DictReader(csvfile)
            for row in reader:
                # Use project name as key and store all info including id (if available)
                existing_data[row['project']] = {
                    'id': row.get('id', None),
                    'due': row['due'],
                    'done': row['done'],
                    'time_submitted': row['time_submitted']
                }
    return existing_data


def store_deadlines_to_csv(csv_filename, deadlines):
    """Stores or updates deadlines in CSV file, preserving 'done' and 'time_submitted' and adding an 'id' column."""
    # Read existing data (if file exists)
    existing_data = read_existing_csv(csv_filename)
    
    # Determine next available ID based on existing entries
    existing_ids = []
    for data in existing_data.values():
        try:
            if data.get('id'):
                existing_ids.append(int(data['id']))
        except ValueError:
            pass
    next_id = max(existing_ids) + 1 if existing_ids else 0
    
    # Define CSV header with 'id'
    fieldnames = ['id', 'project', 'due', 'done', 'time_submitted']
    rows_to_write = []
    
    for project_name, due_date in deadlines:
        try:
            # Parse the due date; adjust year and time as needed
            due_datetime = datetime.strptime(due_date, "%m/%d").replace(year=2025, hour=23, minute=59, second=59)
            due_datetime_iso = due_datetime.isoformat()
            
            if project_name in existing_data and existing_data[project_name].get('id'):
                # Use the existing ID and preserved fields
                assignment_id = existing_data[project_name]['id']
                done_status = existing_data[project_name]['done']
                time_submitted = existing_data[project_name]['time_submitted']
            else:
                # Assign a new ID if it doesn't exist yet
                assignment_id = str(next_id)
                next_id += 1
                done_status = 'False'
                time_submitted = ''
            
            rows_to_write.append({
                'id': assignment_id,
                'project': project_name,
                'due': due_datetime_iso,
                'done': done_status,
                'time_submitted': time_submitted
            })
        except ValueError as e:
            print(f"Date parsing error: {e}")
            print(f"Problematic date: '{due_date}' for project '{project_name}'")
    
    # Write updated data to the CSV file with the new header
    with open(csv_filename, 'w', newline='') as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows_to_write)


def print_csv_contents(csv_filename):
    """Prints the contents of the CSV file."""
    if os.path.exists(csv_filename):
        with open(csv_filename, 'r', newline='') as csvfile:
            reader = csv.DictReader(csvfile)
            print("\nCSV contents:")
            for row in reader:
                print(f"Project: {row['project']}, Due: {row['due']}, Done: {row['done']}, Time Submitted: {row['time_submitted']}")
    else:
        print(f"CSV file '{csv_filename}' does not exist.")

if __name__ == "__main__":
    url = "https://cs10.org/sp25/"
    csv_filename = "deadlines.csv"
    deadlines = scrape_cs10_deadlines(url)
    if deadlines:
        print("Deadlines found:")
        for project_name, due_date in deadlines:
            print(f"{project_name}; {due_date}")
        store_deadlines_to_csv(csv_filename, deadlines)
        print(f"Deadlines have been stored/updated in the CSV file '{csv_filename}'")
        print_csv_contents(csv_filename)
    else:
        print("No deadlines found on the page.")