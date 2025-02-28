# CS10 Deadlines Manager

This project consists of Python scripts to scrape, manage, and view CS10 assignment deadlines from the course website. It uses a SQLite database to store and track assignment information.

## Scripts Overview

1.  **`cs10_scraper.py`**:
    * Scrapes assignment deadlines from the CS10 course website (`https://cs10.org/sp25/`).
    * Initializes or updates an SQLite database (`deadlines.db`) with the scraped deadlines.
    * Preserves the `done` and `time_submitted` status of existing assignments.
    * Adds new assignments to the database.
2.  **`assignment_checker.py`**:
    * Provides functionality to check and manage assignment deadlines.
    * Displays overdue, upcoming, and completed assignments.
    * Calculates and displays the next upcoming deadline.
    * Allows marking assignments as "done" and resetting all assignments.
    * Accepts command-line arguments for manual date/time input and assignment updates.
3.  **`db_viewer.py`**:
    * Prints the entire contents of the `deadlines.db` SQLite database to the console.
    * Displays all columns and rows in a readable format.

## Setup and Usage

### Prerequisites

* Python 3.x
* `requests` library (`pip install requests`)
* `beautifulsoup4` library (`pip install beautifulsoup4`)

### Running the Scripts

1.  **Scraping and Updating Deadlines:**
    * Run `cs10_scraper.py` to scrape and update the database:
        ```bash
        python cs10_scraper.py
        ```
    * This will create or update the `deadlines.db` file with the latest assignment information.

2.  **Checking and Managing Assignments:**
    * Run `assignment_checker.py` to view deadlines and manage assignments:
        ```bash
        python assignment_checker.py
        ```
    * This will display overdue, upcoming, and completed assignments, as well as the next upcoming deadline.
    * **Optional arguments:**
        * `--date YYYY-MM-DD`: Specify a manual date.
        * `--time HH:MM:SS`: Specify a manual time.
        * `--update ID`: Mark an assignment with the given ID as "done".
        * `--reset`: Reset all assignments to "not done".
        * Example:
            ```bash
            python assignment_checker.py --update 1
            python assignment_checker.py --date 2025-03-15 --time 12:00:00
            python assignment_checker.py --reset
            ```

3.  **Viewing Database Contents:**
    * Run `db_viewer.py` to print the database contents:
        ```bash
        python db_viewer.py
        ```
    * This will display all rows and columns of the `deadlines.db` database.

### Database Structure

The `deadlines.db` SQLite database contains a table named `deadlines` with the following columns:

* `id`: Integer, primary key, auto-increment.
* `project`: Text, unique (assignment name).
* `due`: Text (ISO format datetime string).
* `done`: Boolean (0 or 1).
* `time_submitted`: Datetime (ISO format datetime string, or NULL).

### Future Improvements

* Integrate with a React frontend for a user-friendly interface.
* Add features for reminders and notifications.
* More robust error handling.
* More robust website scraping.