import os
import csv
import time
import re
# from dotenv import load_dotenv
from pathlib import Path
from twilio.rest import Client
from twilio.base.exceptions import TwilioRestException

# Import shared settings
import sys
SERVICES_DIR = Path(__file__).resolve().parent.parent
if str(SERVICES_DIR) not in sys.path:
    sys.path.append(str(SERVICES_DIR))

from shared import settings
from shared.delivery_logger import log_sms_delivery

# load_dotenv()

ACCOUNT_SID = settings.TWILIO_ACCOUNT_SID
AUTH_TOKEN = settings.TWILIO_AUTH_TOKEN
MESSAGING_SERVICE_SID = settings.TWILIO_MESSAGING_SERVICE_SID

CSV_FOLDER = Path(os.getenv("CSV_FOLDER", r"text-service\message_requests"))


def normalize_us_number(s):
    return "+1" + re.sub(r"\D", "", s)

def parse_csv_to_dict(file_path):
    """
    input: a Path to a CSV in the message_requests folder
    return: a dictionary {phone_number: message}
    """
    dict = {}
    with file_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            return dict
        
        phone_col = reader.fieldnames[3]
        message_col = reader.fieldnames[-1]

        for row in reader:
            phone_number = (row.get(phone_col) or "").strip()
            message = (row.get(message_col) or "").strip()
            dict[normalize_us_number(phone_number)] = message
    return dict

def send_text_messages():
    """
    Read every CSV in CSV_FOLDER and send each {number: message}.
    """
    client = Client(ACCOUNT_SID, AUTH_TOKEN)

    if not CSV_FOLDER.exists():
        raise FileNotFoundError(f"CSV folder not found: {CSV_FOLDER}")

    for csv_path in CSV_FOLDER.glob("*.csv"):
        mapping = parse_csv_to_dict(csv_path)
        for to, body in mapping.items():
            try:
                message = client.messages.create(
                        body=body,
                        to=to,
                        messaging_service_sid=MESSAGING_SERVICE_SID
                )
                print(f"SMS sent to {to}, SID: {message.sid}")
                log_sms_delivery(
                    recipient=to,
                    status="sent",
                    twilio_sid=message.sid
                )
                time.sleep(0.25)
            except TwilioRestException as e:
                print(f"TWILIO ERROR for {to}: {e.status} {e.code} {e.msg}")
                log_sms_delivery(
                    recipient=to,
                    status="failed",
                    error_message=e.msg,
                    error_code=str(e.code)
                )
            except Exception as e:
                print(f"ERROR for {to}: {e}")
                log_sms_delivery(
                    recipient=to,
                    status="failed",
                    error_message=str(e)
                )

if __name__ == "__main__":
    send_text_messages()