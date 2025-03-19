# CS10 Scraper and Assignment Checker

This repository contains two Python scripts designed to manage CS10 course deadlines and track assignment completion: `cs10_scraper.py` and `assignment_checker.py`.

## `cs10_scraper.py`

This script scrapes assignment deadlines from the CS10 course website and stores them in an SQLite database (`deadlines.db`).

### Functionality

* **Scraping Deadlines:**
    * Fetches the CS10 course webpage.
    * Parses the HTML to extract assignment names and due dates.
    * Stores or updates this information in the `deadlines.db` SQLite database.
* **Database Management:**
    * Initializes the `deadlines.db` database if it doesn't exist.
    * Updates existing deadline entries while preserving the assignment completion status (`done`) and submission time (`time_submitted`).
    * Prints the database contents to the console after updates.
* **Date Handling:**
    * Converts scraped date strings to datetime objects and stores them in ISO format.
    * Adds year to due dates, and sets the time to 23:59:59.

### How to Run

1.  **Ensure Dependencies:** Make sure you have `requests`, `beautifulsoup4`, and `sqlite3` installed. You can install them using pip:

    ```bash
    pip install requests beautifulsoup4
    ```

2.  **Run the Script:**

    ```bash
    python cs10_scraper.py
    ```

    * This will scrape the deadlines from the CS10 course website, update the `deadlines.db` database, and print the updated database contents to the console.

## `assignment_checker.py`

This script manages assignment completion statuses in the `deadlines.db` database and updates a corresponding CSV file (`deadlines.csv`).

### Functionality

* **Updating CSV:**
    * Exports the contents of the `deadlines.db` database to a CSV file (`deadlines.csv`).
    * This CSV file reflects the current assignment statuses.
* **Marking Assignments as Done:**
    * Updates the `done` status and submission time for a specific assignment in the database.
    * Updates the CSV file after marking an assignment as done.
* **Resetting Assignments:**
    * Resets the `done` status for all assignments in the database.
    * Updates the CSV file after resetting assignments.
* **Command-Line Arguments:**
    * `db_name` (optional): Specifies the path to the SQLite database file (defaults to `deadlines.db`).
    * `--update <assignment_id>`: Marks the assignment with the specified ID as done.
    * `--reset`: Resets all assignments to not done.

### How to Run

1.  **Ensure Dependencies:** Ensure `sqlite3` and `csv` are available (these are standard Python libraries).
2.  **Update a Specific Assignment:**

    ```bash
    python assignment_checker.py --update <assignment_id>
    ```

    * Replace `<assignment_id>` with the ID of the assignment you want to mark as done (found in the database or CSV).
    ex: ```bash
    python assignment_checker.py --update 1
    ```

3.  **Reset All Assignments:**

    ```bash
    python assignment_checker.py --reset
    ```

    * This will reset all assignments to not done.

4.  **Using a Different Database File:**

    ```bash
    python assignment_checker.py <path_to_database.db> --update <assignment_id>
    ```

    * Or
    ```bash
        python assignment_checker.py <path_to_database.db> --reset
    ```

    * Replace `<path_to_database.db>` with the path to your database file.

5.  **Updating the CSV without other changes**

    ```bash
    python assignment_checker.py
    ```
    * If no arguments are provided, the csv will be updated to reflect the database state.
