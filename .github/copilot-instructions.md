# AutoRemind Copilot Instructions

## Project Overview
AutoRemind is a microservice that automates student notifications about assignment deadlines. It integrates with Learning Management Systems (LMS) via the GradeSync API and delivers messages through Discord, SMS, and Email.

**Data Flow**: LMS data → `gradesync_input` pipeline → CSV message requests → individual service handlers (`email-service`, `discord_service`, `text-service`) → student notifications.

## Architecture

### Core Components
1. **Frontend** (`index.html`, `login.html`): Settings UI for students to configure notification preferences (channels, frequency, assignment status filters)
2. **Backend** (`server.js`): Node.js dev server (Vercel in production); routes settings POST requests to API handlers
3. **API Handler** (`api/reminders/settings.js`): Validates settings payload, stores to Supabase `notification_preferences` table (using email as unique SID key)
4. **Data Pipeline** (`gradesync_input/`): 
   - `gradesync_to_df.py`: Fetches assignment data from Google Sheets, outputs per-assignment CSVs to `output_files.csv`
   - `df_to_message_requests.py`: Filters CSV by due dates and notification frequency, generates message request CSVs
   - `main.py`: Orchestrates both steps daily via cron
5. **Notification Services** (parallel, async):
   - `email-service/`: Gmail API sender; reads `message_requests/` CSVs, sends personalized emails
   - `discord_service/`: Sends Discord DMs (via Discord API or webhooks)
   - `text-service/`: SMS sender (Twilio)

### Data Stores
- **Supabase** (`SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`): Stores `notification_preferences` (email-keyed)
- **Local CSVs**: Intermediate message requests (`message_requests/` dirs in each service); transient, generated daily

## Environment Setup

### Required Environment Variables
```bash
SUPABASE_URL="https://<project-id>.supabase.co"
SUPABASE_SERVICE_ROLE_KEY="<service-role-key>"  # DO NOT COMMIT
```
Store in `.env.local` (gitignored; see `.gitignore`).

### Startup
```bash
npm install
npm run test-server          # Runs server.js locally on :3000
# OR
npm run dev                  # Vercel dev environment
```

## Coding Patterns & Conventions

### Frontend Logic (index.html)
- **Toggle + Input Reveal**: Use `bindToggle(checkboxId, fieldId)` pattern to show/hide channel input fields conditionally
- **Channel Configuration**: `channelConfigs` array defines (checkbox, input field, validation regex, error message) tuples; extensible for new channels
- **Validation**: Each channel has a custom `validate()` function (e.g., email regex, phone length); failures trigger alerts and field focus
- **Payload Collection**: `collectSettingsPayload()` builds `{ channels: { email: "...", discord: "...", sms: "..." }, days_before: N, include_incomplete: bool }`; throws `Error('validation')` on failure
- **Modal Control**: Agreement/unsubscribe modals use inline event listeners (`display: flex/none` toggle)

### Backend Patterns (Node.js / serverless)
- **Handler Interface**: All API handlers export `default async function handler(req, res)` (Vercel convention)
- **Request Shape**: `{ method, body }` (body already parsed JSON in serverless; raw in dev server)
- **Response Pattern**: `res.status(code).json(data)` chaining
- **Supabase Usage**: Always check `!supabaseUrl || !supabaseKey` before creating client; handle conflict errors (`code === '23505'`) for duplicate entries
- **Error Responses**: Return `{ error: "message", details?: "..." }` on failure

### Python Services (email-service, gradesync_input, etc.)
- **CSV Handling**: Expect `message_requests/*.csv` with columns: `email`, `assignment`, `name` (or `first_name`/`last_name`), `sid`
- **Environment Variable Defaults**: Use `.get()` with sensible defaults (e.g., `MESSAGE_REQUESTS_DIR` → `"message_requests"`)
- **Logging**: Use Python `logging` module; configure both file handler (`.log` files in service root) and console output
- **Error Handling**: Graceful degradation (skip individual emails/students; log warnings, continue with batch)
- **Google API Auth**: Store credentials in `config/credentials.json` (gitignored); document setup steps in service README

### CSV / Data Pipeline Conventions
- **Delimiter & Encoding**: UTF-8, comma-delimited CSVs
- **Column Standardization**: `gradesync_to_df.py` normalizes headers (lowercased, spaces → underscores if needed)
- **Email as Unique Key**: Used to identify students across systems; treat as primary identifier in Supabase

## Adding a New Notification Channel

1. **Frontend** (`index.html`):
   - Add checkbox + input field pair with IDs (e.g., `ch-slack`, `slack-field`)
   - Add to `channelConfigs` array with validation function
   - Call `bindToggle('ch-slack', 'slack-field')`

2. **Backend** (`api/reminders/settings.js`):
   - Extract `channels.slack` from payload
   - Pass to downstream service

3. **Service** (new folder, e.g., `slack-service/`):
   - Create `main.py` (or equivalent) following email-service pattern
   - Read `message_requests/*.csv` from parent or shared location
   - Implement API client auth and sending logic
   - Add comprehensive logging and error handling

## Testing & Debugging

### Server Development
```bash
npm run test-server  # Runs server.js on localhost:3000
curl -X POST http://localhost:3000/api/reminders/settings \
  -H "Content-Type: application/json" \
  -d '{"channels":{"email":"test@example.com"},"days_before":5,"include_incomplete":false}'
```

### Python Services
```bash
# From service directory
python main.py              # Full pipeline
python -c "import <module>; <module>.test_function()"  # Unit test helpers
# Check .log files for detailed logs
```

### Supabase
- Verify `SUPABASE_SERVICE_ROLE_KEY` has table permissions: `INSERT`, `SELECT`
- Check `notification_preferences` table schema and unique constraints
- Test insert with duplicate email to verify `code === '23505'` handling

## Integration Points & External Dependencies

- **Supabase**: Schema must include `notification_preferences(sid, notification_frequency, name, last_name, ...)`
- **Google Sheets API**: Used by `gradesync_input`; credentials in `config/credentials.json`
- **Gmail API**: Service account with domain-wide delegation for `email-service`
- **Discord API**: Bot token or webhook for `discord_service`
- **Twilio**: Account SID & auth token for SMS in `text-service`
- **Vercel**: Production deployment; serverless functions auto-routed

## Common Gotchas

- **Email Uniqueness**: Supabase constraint on `notification_preferences.sid` (email); code catches 23505 conflict
- **Environment Variables in Vercel**: Must be set in Vercel dashboard; `.env.local` only for local dev
- **CSV File Paths**: Each service maintains its own `message_requests/` dir; not shared across services (intentional for isolation)
- **Logging in Serverless**: Avoid excessive logging; check CloudWatch/Vercel logs, not local files
- **Frontend Validation**: Happens before POST; custom regexes for phone/email (don't rely on HTML5 validation alone)

## Key Files Reference

| File | Purpose |
|------|---------|
| `index.html` | Main UI; settings form with modal agreements |
| `server.js` | Dev server; routes to API handlers |
| `api/reminders/settings.js` | Validates & stores user preferences |
| `gradesync_input/main.py` | Orchestrates data pipeline (daily cron) |
| `email-service/main.py` | Sends Gmail reminders from CSV batches |
| `package.json` | Node.js dependencies & scripts |
| `.env.local` | Local secrets (not committed) |
