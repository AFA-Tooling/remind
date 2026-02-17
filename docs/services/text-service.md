# Text Service (SMS)

The Text Service sends SMS reminders via Twilio.

## Features

- Reads CSV files from `services/text-service/message_requests/`.
- Sends SMS messages to US phone numbers.
- Uses Twilio Messaging Service for handling opt-outs and regulations.

## Configuration

Required environment variables in `.env.local`:

```bash
TWILIO_ACCOUNT_SID="your-account-sid"
TWILIO_AUTH_TOKEN="your-auth-token"
TWILIO_MESSAGING_SERVICE_SID="your-messaging-service-sid"
```

## Usage

1.  Ensure valid CSV files exist in `services/text-service/message_requests/`.
    *   **Note**: Currently, `db_fetch.py` does not automatically generate CSVs in this specific folder structure by default. You may need to copy them or configure `db_fetch.py` to output here.
2.  Run the script:

```bash
python3 services/text-service/send_text_reminders.py
```
