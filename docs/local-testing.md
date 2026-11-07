# Local testing with the Firestore emulator

Run the pipeline and web app on your laptop against a local, throwaway Firestore
instead of production.

## One-time setup

1. Install Java 11+ (the emulator runs on it) and the Python deps:
   `pip install -r services/requirements.txt`.
2. Add this line to your **local** `.env.local`:
   ```
   USE_FIRESTORE_EMULATOR=true
   ```
   While it's there, every Python script and the web app talk to the emulator at
   `127.0.0.1:8080`, even in a terminal where you forgot to set anything. If the
   emulator isn't running they fail to connect; they never fall through to
   production. Delete the line to go back to production.

   Deploys never see this flag: the deploy scripts copy only named keys out of
   `.env.local`, and `.env.local` is excluded from the Cloud images.

## Every session

```bash
# Terminal 1: start the emulator (UI at http://127.0.0.1:4000)
npm run emulator

# Terminal 2: seed fake data, then generate reminders
python services/gradesync_input/seed_emulator.py --me you@berkeley.edu
python services/gradesync_input/db_fetch.py
```

`db_fetch.py` prints each student's draft reminder. The seed script prints the
reminders you should expect, so compare the two. Add `--gmail-csv` / `--sms-csv` /
`--discord-csv` to also write the message-request CSVs.

On Windows, if a script crashes with `UnicodeEncodeError`, run
`$env:PYTHONIOENCODING = "utf-8"` first (the pipeline prints emoji).

Emulator data is wiped when the emulator stops; re-run the seed script.

Seed flags: `--no-reset` keeps the existing data. `--old-shape` writes the
single-course shape production holds today (no `course_codes` lists on
`class_roster` / `students`, and course-less `assignment_submissions` IDs), so you
can check the new code still reads it. The reminders should come out the same
either way. After `--old-shape`, run
`python services/gradesync_input/sync_student_courses_cli.py --apply` to watch the
students get their `course_codes` lists filled in from the roster.

## Web app

`npm start` with the flag set. Sign-in still uses real Firebase Auth, but all
data comes from the emulator, and the app runs **without** a service account in
this mode. Seed with `--me <your login email>` so the dashboard has a student
doc for you.

## What's blocked in emulator mode

- `services/email-service/main.py`, `services/text-service/send_text_reminders.py`
  and `services/discord_service/send_discord_reminders.py` refuse to run.
  Emulator data can hold real contact info (see below), so nothing is sent from it.
- `seed_emulator.py` refuses to run unless it points at a local emulator.

## Real data in the emulator

`gradesync_to_db.py` works in emulator mode too: it reads the real Google Sheets
(read-only) and writes the real rosters and submissions into the emulator.
That's useful for realistic tests, but it puts real student names and emails on
your laptop, so prefer the seed data unless you need the real shape.

## The seed data

`seed_emulator.py` writes the current one-course-per-student shape, with all
dates relative to today. Students are `@example.com`:

| Student | Courses (intended) | What it tests |
|---|---|---|
| alice.multi | CS61A + CS61C | Multi-course; same-named "Lab 1" in both |
| ben.61a | CS61A | Single-course control; one assignment already submitted |
| cara.61c | CS61C | Labs turned off in category prefs |
| dev.waitlist | CS10 | Study group 2, access closed → gated out |
| erin.multi.split | CS61C + CS10 | Different study group per course |
| finn.nocourse | none | Unroutable-student warning |

The current shape can only store one course per student, so multi-course students
are seeded with their first course. Their full intended courses and per-course
study groups are kept in `_seed_*` fields for later multi-course tests.
