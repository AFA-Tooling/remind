# Retrieval-Augmented Generation (RAG) Implementation

This repository contains a basic implementation of a Retrieval-Augmented Generation (RAG) system.

## Setup Instructions

To run this project, follow these steps:

1.  **Clone the Repository:**

2.  **Install Dependencies:**

    * **Using pip (and requirements.txt):**

        ```bash
        pip install -r requirements.txt
        ```

3.  **Obtain OpenAI API Key:**

    * You will need an OpenAI API key to run the code. Contact [TBD] to receive the key.

4.  **Create `.env` File:**

    * In the root directory of the project, create a file named `.env`.

5.  **Add API Key to `.env`:**

    * Inside the `.env` file, add your OpenAI API key in the following format:

        ```
        OPENAI_API_KEY=sk-your_actual_api_key_here
        ```

        * Replace `sk-your_actual_api_key_here` with the API key you received.

6.  **Security Note:**

    * **Crucially, do not commit your `.env` file to version control.** Add `.env` to your `.gitignore` file to prevent it from being pushed to remote repositories.

7.  **Run the Code:**

    * Execute the Python script (`python api_connect.py`).

