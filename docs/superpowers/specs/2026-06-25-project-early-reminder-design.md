# Design: "Remind me a day earlier for projects"

**Date:** 2026-06-25
**Status:** Approved

## Problem

In CS61A (and similar courses), submitting a **project** one day early earns extra
credit. AutoRemind currently sends every reminder relative to the assignment's real
due date, so students aren't nudged toward that early-submission window. We want an
opt-in setting that shifts a student's project reminders one day earlier.

## Behavior

A per-student boolean preference. When **on**, any assignment whose derived category is
`Project` is treated as if its deadline were **one day earlier**. The student's entire
`days_before_deadline` schedule then keys off that shifted date, so every reminder for
that project lands a day sooner. Non-project assignments are unaffected.

This is a *schedule shift*, not an extra reminder: the count of reminders is unchanged,
they simply target the early (extra-credit) deadline.

### Intended consequence

Because the effective deadline moves a day earlier, a project transitions to "past due"
(`delta_days < 0`, which is skipped) one day sooner — on the real due date itself.
This is intended: the student is deliberately targeting the early-submission deadline.

## Scope

- **Audience:** Roster students only. The toggle appears alongside the existing
  CS61A category checkboxes (`#cs61a-section`), which only render for roster students.
- **Category covered:** Only the `Project` category, as produced by the existing
  `derive_assignment_category()` (the default fallback — e.g. Hog, Cats, Ants, "Project 1").
  Lab / Homework / Midterm are not affected.

## Data model

New field on the `students/{email}` Firestore document:

- `project_early_reminder` (boolean, default `false`)

Stored next to `category_prefs`, gated to roster students the same way.

## Components

### 1. Python pipeline — `services/gradesync_input/db_fetch.py`

In `build_assignment_payload()`:

- The assignment category is already derived via `derive_assignment_category()` and the
  `category_prefs` gate already runs (around line 590).
- The personal deadline is computed via `compute_personal_deadline()` (around line 602/638).
- **Add:** after the personal deadline is computed, if `category == "Project"` **and**
  `student.get("project_early_reminder")` is truthy, subtract one day from the deadline
  value used for the `delta_days` computation (line ~640).
- Everything downstream — the exact-match gate `if delta_days != freq_days: return None`
  (line 661) and the past-due check `if delta_days < 0` — is unchanged. It simply keys
  off the shifted date.

The shift must apply only to the date used for `delta_days`; it should not corrupt any
deadline value reported in the message payload unless that already reflects the personal
deadline (match existing behavior — keep the displayed/effective deadline consistent with
how the personal-deadline offset is currently surfaced).

### 2. Node API — `src/api/reminders/settings.js`

- Read `project_early_reminder` from the request body.
- Coerce to a strict boolean.
- Persist it in the same merge write used for `category_prefs`, gated to roster students
  (mirror the existing `category_prefs` handling).

### 3. Node API — `src/api/reminders/get.js`

- Include `project_early_reminder` in the returned `data`, defaulting to `false` when absent.

### 4. Frontend — `public/index.html`

- Add a single checkbox inside the existing roster-only `#cs61a-section`, below the four
  category checkboxes:
  > "Remind me a day earlier for projects (turn in early for extra credit)."
- `collectSettingsPayload()`: read the checkbox `.checked` into the payload as
  `project_early_reminder`.
- `populateForm()`: set the checkbox `.checked` from `data.project_early_reminder`
  (default unchecked).

## Testing

- **Python unit test:** exercise `build_assignment_payload()` (or the deadline computation)
  for a `Project` assignment with `project_early_reminder` on vs. off, asserting the
  reminder fires exactly one day earlier when on, and that a non-project assignment is
  unaffected by the flag.
- **Manual round-trip:** toggle the checkbox in the dashboard as a roster student, save,
  reload, and confirm it persists through the `settings` → `get` round-trip.

## Out of scope

- Per-assignment override of the early-reminder behavior.
- Applying the shift to non-project categories.
- Exposing the toggle to non-roster students.
