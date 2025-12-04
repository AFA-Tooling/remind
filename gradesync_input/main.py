"""
Main orchestration script.
1. Runs db_fetch.py to generate the Discord CSV.
2. Runs send_discord_reminders.py to send the messages.
"""

import sys
import subprocess
from pathlib import Path

def main():
    # 1. Setup Paths
    current_dir = Path(__file__).resolve().parent
    project_root = current_dir.parent
    
    script_fetch = current_dir / "db_fetch.py"
    script_send = project_root / "discord_service" / "send_discord_reminders.py"

    # 2. Verify scripts exist
    if not script_fetch.exists():
        print(f"❌ Error: Could not find {script_fetch}")
        return
    if not script_send.exists():
        print(f"❌ Error: Could not find {script_send}")
        return

    # 3. Run Step 1: db_fetch.py
    print("--------------------------------------------------")
    print("STEP 1: Fetching Data & Generating Reminders CSV")
    print("--------------------------------------------------")
    
    # We must pass --discord-csv so db_fetch generates the file 
    # required by the sender script.
    fetch_cmd = [sys.executable, str(script_fetch), "--discord-csv"]
    
    try:
        # check=True raises an exception if the script fails (returns non-zero)
        subprocess.run(fetch_cmd, check=True)
    except subprocess.CalledProcessError as e:
        print(f"\n❌ Step 1 Failed. Aborting. (Exit code: {e.returncode})")
        return

    # 4. Run Step 2: send_discord_reminders.py
    print("\n--------------------------------------------------")
    print("STEP 2: Sending Discord Messages")
    print("--------------------------------------------------")

    send_cmd = [sys.executable, str(script_send)]

    try:
        subprocess.run(send_cmd, check=True)
    except subprocess.CalledProcessError as e:
        print(f"\n❌ Step 2 Failed. (Exit code: {e.returncode})")
        return

    print("\n--------------------------------------------------")
    print("✅ AUTOMATION COMPLETE")
    print("--------------------------------------------------")

if __name__ == "__main__":
    main()