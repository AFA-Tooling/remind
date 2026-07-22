# Auto-enroll consented study participants

**Date:** 2026-07-22
**Status:** Approved

## Problem

Consent and delivery are wired to two different collections, and nothing bridges
them.

Consenting writes a doc to `study_participants` (via the admin CSV upload or the
manual add on `/admin`). The daily pipeline, however, iterates the `students`
collection — `db_fetch.py` reads `students`, computes which reminders are due,
and writes the per-channel CSVs. A `students` doc is only ever created by
`POST /api/reminders/register`, which fires on first sign-in to the dashboard.

So a student who consents to the study receives nothing until they separately
discover the app and sign in. Even then the old registration defaults left
`email_pref: false`, so they received nothing until they also opened the
settings page and enabled a channel.

The study requires that **everyone in Group 1 receives at least email
reminders**, with the app being an optional upgrade path for students who want
to change the cadence or add text/Discord.

## Goals

1. Consenting is sufficient to receive email reminders. No sign-in required.
2. Every already-consented student is backfilled to the same state.
3. Every reminder email carries a link to the dashboard explaining how to manage
   preferences and add other channels.

## Non-goals

- Changing who is *allowed* to receive notifications. The study gate
  (`apply_study_gate` in `db_fetch.py`) remains the sole sender-side authority:
  Group 1 only, unless `study_config/state.access_open` is true.
- Sending an enrollment/welcome email. The first reminder does the explaining.
- Overriding a student who explicitly turned email off.

## Design

### 1. Where enrollment happens

Three touchpoints, all sharing one defaults builder.

**`src/api/students/defaults.js`** (new) hoists `DEFAULT_COURSE_CODE`,
`resolveCourseCode`, and `buildNewStudent` out of `register.js` so the consent
path and the login path produce byte-identical documents.

**`src/api/admin/study.js`, `POST ?action=consent`** — after writing the
`study_participants` docs, create a `students` doc for any submitted email that
does not already have one. This keys off the full cleaned email list, not just
`toAdd`, so re-uploading a CSV repairs a participant whose student doc is
missing. `course_code` resolves from `class_roster`, exactly as registration
does. The JSON response gains an `enrolled` count.

**`src/api/reminders/register.js`** — logic unchanged, but inherits the new
defaults from `defaults.js`, so a student who signs in through a path that
skipped consent-time enrollment still lands email-enabled.

Student docs are created for **both groups**. The study gate drops Group 2 and
unassigned reminders before any CSV is written, so nobody receives mail early;
flipping `access_open` or running randomization then activates Group 2 with no
second migration.

`POST ?action=remove` needs no change: deleting the participant doc removes the
email from the gate's allowlist, so delivery stops.

### 2. Default preference shape

| Field | New value | Was |
|---|---|---|
| `email_pref` | `true` | `false` |
| `days_before_deadline` | `3` | `1` |
| `category_prefs` | all five `true` | absent |
| `release_reminder` | `true` | `true` |
| `project_early_reminder` | `false` | absent |
| `phone_pref` / `discord_pref` | `false`, targets `null` | same |
| `enrolled_via` | `'consent'` or `'signup'` | — |

Two behaviors this implies:

- `days_before_deadline: 3` fires on an **exact** match
  (`delta_days == freq_days`, `db_fetch.py`), so a student gets one email per
  assignment at T-3, not a daily nag across a three-day window. This is
  pre-existing behavior, restated here because "3 days before" reads like a
  window.
- `category_prefs` all-true is functionally identical to the field being absent
  (`db_fetch.py` treats a missing key as enabled), but writing it explicitly
  makes the dashboard render the boxes checked.

### 3. Existing student docs

About 58 students already have docs created by the old registration defaults,
carrying `email_pref: false`. Some never opened the settings page; some may have
deliberately turned email off. Only the former should be flipped.

The discriminator is `created_at === updated_at`. This is reliable because
`register.js` stamps both fields with the same timestamp at creation, and
`settings.js` always writes a fresh `updated_at` and never writes `created_at`.
A doc whose timestamps still match has never been through a settings save.

An explicit opt-out is never overridden. Those emails are reported by the
backfill so they can be handled by hand.

### 4. Backfill script

`services/gradesync_input/backfill_consent_enrollment.py`, following the
`backfill_course_code.py` convention: dry run by default, `--apply` to commit,
with the decision logic in a pure function so it is testable without Firestore.

```
plan_enrollment(participants, students, roster, default_course_code)
  -> { create: [...], activate: [...], skipped_optout: [...], no_change: n }
```

| Case | Action |
|---|---|
| No `students` doc | **create** with the full default shape, `enrolled_via: 'consent'` |
| Doc exists, `email_pref` falsy, `created_at == updated_at` | **activate**: set `email_pref`, `days_before_deadline`, `category_prefs` only |
| Doc exists, `email_pref` falsy, timestamps differ | **skip**, listed under an explicit-opt-out heading |
| Doc exists with email already on | no change |

Activate deliberately does not touch `phone_*`, `discord_*`, or
`preferred_first_name`.

The default shape is spelled out twice — once in `defaults.js`, once in the
script — because the two runtimes cannot share code. This mirrors the existing
duplication of `DEFAULT_COURSE_CODE`; each site carries a comment pointing at
the other.

Because `?action=consent` now self-heals, this script is a one-shot for the
current cohort rather than a scheduled job.

### 5. Email footer

`services/shared/settings.py` gains `AUTOREMIND_SITE_URL`, env-overridable,
defaulting to `https://autoremind.eecs.berkeley.edu`.

`db_fetch.py` gains `append_manage_prefs_footer(message)`, applied in
`write_gmail_csv` when building the `message_requests` column. Not in
`compose_message`, which is shared with Discord and SMS; not in the email
service, which sends `message_body` verbatim. Keeping it in `db_fetch` means the
CSV and the delivery log hold exactly what was sent.

Copy, appended after the existing "reach out to course staff" line:

```
—
Manage your reminders at https://autoremind.eecs.berkeley.edu
Sign in with your Berkeley email to change how far ahead you're notified,
pick which assignment types you hear about, or add text and Discord reminders.
```

### 6. Testing

**JS** (`npm test`, `node --test`):

- `register.test.js` imports from `defaults.js`; the `days_before_deadline`
  assertion becomes `3`, plus new assertions for `email_pref` and
  `category_prefs`.
- New `src/api/admin/study.test.js` with a small in-memory Firestore fake.
  `runStudyAction` already accepts an injectable `db` for this purpose but no
  test exercised it. Cases: consent creates student docs; an existing student
  doc is left untouched; `course_code` comes from the roster with a default
  fallback; re-uploading an existing participant repairs a missing student doc.

**Python** (`pytest`):

- `test_backfill_consent_enrollment.py` covering all four `plan_enrollment`
  buckets, especially that divergent timestamps land in `skipped_optout`.
- A footer assertion alongside the existing gmail-CSV tests.

`test_reminder_delivery_gaps.py` must stay green — it is the regression signal
that Group 2 still receives nothing.

## Rollout

1. Deploy the code (consent path + register defaults + email footer).
2. Run `backfill_consent_enrollment.py` as a dry run, review the
   explicit-opt-out list.
3. Re-run with `--apply`.
4. Confirm the next daily run's recipient count against the Group 1 size.
