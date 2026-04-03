# AutoRemind

**Automated reminders for students, powered by a single source of truth.**

AutoRemind is a modular notification system that sends personalized assignment reminders via Email, Discord, and SMS. It integrates with GradeSync (Google Sheets) for class-wide deadline tracking and bCourses (Canvas LMS) for per-student assignment sync.

## Features

- **Multi-channel reminders** — Email, SMS (Twilio), and Discord DMs
- **bCourses integration** — Students connect their bCourses account via OAuth; upcoming assignments are synced automatically
- **GradeSync integration** — Shared class deadlines ingested from Google Sheets
- **Student dashboard** — Configure reminder channels, preferred name, and how many days before a deadline to be notified
- **Admin dashboard** — View all students, deadlines, resources, and message delivery logs; manage assignment resources via a CRUD interface
- **Daily pipeline** — Cloud Run Job syncs bCourses data and sends reminders on a schedule

## Quick Start

### 1. Install dependencies

```bash
pip install -r services/requirements.txt
npm install
```

### 2. Configure environment

```bash
cp .env.example .env.local
# Fill in your credentials (see env var reference below)
```

### 3. Run locally

```bash
npm run dev        # Web server at http://localhost:3000
```

### 4. Run the reminder pipeline manually

```bash
python3 services/gradesync_input/main.py
```

This runs three steps in order:
1. **Canvas sync** — refreshes bCourses assignments for all connected students
2. **Reminder generation** — computes which students are within their notification window and drafts messages
3. **Discord + Email delivery** — sends the drafted messages

---

## Architecture

### Node.js Web Server (`src/`)

Serves the student dashboard and REST API. All Firestore access goes through `src/api/firestore.js`.

| Route | Method | Description |
|---|---|---|
| `GET /api/config` | GET | Firebase client credentials |
| `GET /api/reminders/get` | GET | Fetch student settings |
| `POST /api/reminders/register` | POST | Create student doc on first login |
| `POST /api/reminders/settings` | POST | Save reminder preferences |
| `POST /api/reminders/unsubscribe` | POST | Disable notification channels |
| `GET /api/deadlines` | GET | Student's GradeSync deadlines |
| `GET /api/resources` | GET | Resources for an assignment |
| `GET /api/canvas/auth` | GET | Start bCourses OAuth flow |
| `GET /api/canvas/callback` | GET | bCourses OAuth callback |
| `POST /api/canvas/sync` | POST | On-demand bCourses assignment sync |
| `GET /api/canvas/deadlines` | GET | Student's synced bCourses assignments |
| `POST /api/canvas/disconnect` | POST | Remove bCourses connection |
| `GET /api/admin/students` | GET | All registered students (admin only) |
| `GET /api/admin/deadlines` | GET | All deadlines (admin only) |
| `GET /api/admin/resources` | GET/POST/PUT/DELETE | Assignment resources CRUD (admin only) |
| `GET /api/admin/delivery-logs` | GET | Message delivery history (admin only) |

### Python Daily Pipeline (`services/`)

Orchestrated by `services/gradesync_input/main.py`:

1. **Canvas sync** (`services/canvas_sync/canvas_sync.py`) — refreshes `canvas_deadlines` in Firestore for all connected users
2. **Reminder generation** (`services/gradesync_input/db_fetch.py`) — reads `deadlines`, `canvas_deadlines`, and `students`; outputs Discord and Gmail CSVs
3. **Discord delivery** (`services/discord_service/send_discord_reminders.py`)
4. **Email delivery** (`services/email-service/main.py`)

### Firestore Collections

| Collection | Key | Description |
|---|---|---|
| `students` | email | Student preferences and channel settings |
| `deadlines` | `{course}__{assignment}` | Shared GradeSync deadlines |
| `assignment_resources` | auto-id | Study resources linked to assignments |
| `assignment_submissions` | `{assignment}__{student}` | Submission status from GradeSync |
| `canvas_tokens` | email | bCourses OAuth tokens (server-side only) |
| `canvas_deadlines` | `{email}__{assignment_id}` | Per-student synced bCourses assignments |
| `message_delivery_logs` | auto-id | Record of every sent/failed reminder |

---

## bCourses Integration

Students can connect their bCourses account from the dashboard settings page.

1. Student clicks **Connect bCourses** and completes the OAuth flow on bcourses.berkeley.edu
2. Access and refresh tokens are stored in `canvas_tokens` (never exposed to the frontend)
3. Upcoming assignments are synced into `canvas_deadlines` immediately, then refreshed each time the daily pipeline runs
4. Assignments show up on the Assignments page with a **bCourses** badge
5. The reminder pipeline sends notifications for bCourses assignments the same way it does for GradeSync deadlines

**Setup:** Create a developer key in the bCourses admin panel, set the redirect URI to `https://your-domain/api/canvas/callback`, and add `CANVAS_CLIENT_ID`, `CANVAS_CLIENT_SECRET`, and `CANVAS_REDIRECT_URI` to `.env.local`.

---

## Admin Dashboard

Accessible at `/admin.html`. Requires a Google account whose email is listed in `ADMIN_EMAILS`.

- **Overview** — student count, deadline count, resource count, delivery success rate
- **Students** — all registered students with channel preferences
- **Deadlines** — all GradeSync deadlines
- **Resources** — add, edit, and delete assignment resources; assignment name and course code are populated from existing deadlines and resources
- **Delivery Logs** — full message history filterable by channel and status

---

## Environment Variables

See `.env.example` for a full template. Key variables:

| Variable | Used by | Description |
|---|---|---|
| `FIREBASE_PROJECT_ID` | Node + Python | Firebase project ID |
| `FIREBASE_API_KEY` | Node | Client-side Firebase key |
| `FIREBASE_AUTH_DOMAIN` | Node | Firebase auth domain |
| `FIREBASE_SERVICE_ACCOUNT_JSON` | Node | JSON-encoded service account (for firebase-admin) |
| `FIREBASE_SERVICE_ACCOUNT_PATH` | Python | Path to service account JSON file |
| `DISCORD_BOT_TOKEN` | Python | Discord bot token |
| `DISCORD_GUILD_ID` | Python | Discord server ID |
| `TWILIO_ACCOUNT_SID` | Python | Twilio account SID |
| `TWILIO_AUTH_TOKEN` | Python | Twilio auth token |
| `TWILIO_MESSAGING_SERVICE_SID` | Python | Twilio messaging service SID |
| `CANVAS_CLIENT_ID` | Node + Python | bCourses OAuth developer key ID |
| `CANVAS_CLIENT_SECRET` | Node + Python | bCourses OAuth developer key secret |
| `CANVAS_REDIRECT_URI` | Node | OAuth callback URL |
| `CANVAS_DEFAULT_DOMAIN` | Node + Python | Canvas domain (default: `bcourses.berkeley.edu`) |
| `ADMIN_EMAILS` | Node | Comma-separated admin email allowlist |

---

## Project Structure

```
public/          Frontend (HTML/CSS/JS)
  index.html     Student dashboard
  assignments.html  Assignment list with bCourses + GradeSync merge
  admin.html     Admin dashboard
src/
  server.js      HTTP server and routing
  api/
    canvas/      bCourses OAuth + sync handlers
    admin/       Admin API handlers
    reminders/   Student settings handlers
    deadlines/   GradeSync deadlines handler
services/
  gradesync_input/   GradeSync ingestion and reminder pipeline
  canvas_sync/       bCourses API client and sync
  email-service/     Gmail delivery
  discord_service/   Discord DM delivery
  text-service/      SMS delivery
  shared/            Shared config (settings.py, delivery_logger.py)
```

## Deployment

See `docs/deployment.md` for full GCP Cloud Run deployment instructions.

```bash
bash deploy_job.sh           # Deploy the daily reminder job
bash deploy_job.sh --refresh-secrets  # Rotate secrets
```
