import os
import csv
import time
from pathlib import Path
from twilio.rest import Client
from twilio.base.exceptions import TwilioRestException

import sys
SERVICES_DIR = Path(__file__).resolve().parent.parent
if str(SERVICES_DIR) not in sys.path:
    sys.path.append(str(SERVICES_DIR))

from shared import settings
from shared.delivery_logger import log_sms_delivery

ACCOUNT_SID = settings.TWILIO_ACCOUNT_SID
AUTH_TOKEN = settings.TWILIO_AUTH_TOKEN
FROM_NUMBER = "+18556796659"

CSV_FOLDER = Path(os.getenv("CSV_FOLDER", "message_requests"))


def parse_csv(file_path: Path) -> list[dict]:
    rows = []
    with file_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            phone = (row.get("phone_number") or "").strip()
            message = (row.get("text_message") or "").strip()
            if phone and message:
                rows.append({"phone_number": phone, "text_message": message})
    return rows


def send_text_messages():
    client = Client(ACCOUNT_SID, AUTH_TOKEN)

    csv_folder = Path(__file__).resolve().parent / CSV_FOLDER if not CSV_FOLDER.is_absolute() else CSV_FOLDER

    if not csv_folder.exists():
        raise FileNotFoundError(f"CSV folder not found: {csv_folder}")

    csv_files = list(csv_folder.glob("*.csv"))
    if not csv_files:
        print(f"No CSV files found in {csv_folder}")
        return

    total_sent = 0
    total_failed = 0

    for csv_path in csv_files:
        print(f"\nProcessing {csv_path.name}...")
        rows = parse_csv(csv_path)

        if not rows:
            print(f"  No valid rows in {csv_path.name}, skipping")
            continue

        for row in rows:
            to = row["phone_number"]
            body = row["text_message"]
            try:
                msg = client.messages.create(
                    body=body,
                    to=to,
                    from_=FROM_NUMBER,
                )
                print(f"Sent to {to}, SID: {msg.sid}")
                log_sms_delivery(recipient=to, status="sent", twilio_sid=msg.sid)
                total_sent += 1
                time.sleep(0.25)
            except TwilioRestException as e:
                print(f"Twilio error for {to}: {e.status} {e.code} {e.msg}")
                log_sms_delivery(recipient=to, status="failed", error_message=e.msg, error_code=str(e.code))
                total_failed += 1
            except Exception as e:
                print(f"Error for {to}: {e}")
                log_sms_delivery(recipient=to, status="failed", error_message=str(e))
                total_failed += 1

    print(f"\nDone. Sent: {total_sent}, Failed: {total_failed}")


if __name__ == "__main__":
    send_text_messages()
