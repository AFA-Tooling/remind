# Students-tab study-group column — design

**Date:** 2026-07-08

## Goal
Make it easy to see, from the admin dashboard's **Students** tab, which study group each
student belongs to, and to pull the list of students who have never registered for the
research study (so they can be emailed a reminder).

## Background
- **Students** tab reads the `students` Firestore collection (`src/api/admin/students.js`
  → `GET /api/admin/students`), rendered by `loadStudents()` in `public/admin.html`.
- **Research Study** tab reads a separate `study_participants` collection (doc id = email,
  field `group` ∈ {1, 2, null}). Constants live in `src/api/study/studyStatus.js`.
- The two collections are keyed by the same email but are never joined today, so the
  Students table shows no group information.

## Column semantics (4 states)
Join `students` → `study_participants` by normalized email (`trim().toLowerCase()`):

| Condition | `study_group` value | Column label |
|---|---|---|
| participant doc, `group === 1` | `1` | Group 1 |
| participant doc, `group === 2` | `2` | Group 2 |
| participant doc, `group` null/absent | `"unassigned"` | Unassigned (consented, awaiting randomization) |
| no participant doc | `"none"` | N/A (never registered) |

Distinguishing **Unassigned** from **N/A** matters: only N/A students are the ones who
haven't registered and should get a reminder email.

## Changes

### 1. `src/api/admin/students.js` — server-side join
- Read the `study_participants` collection once alongside `students`.
- Build a `Map<normalizedEmail, group|null>` (existence in the map = registered).
- Attach `study_group` (`1` | `2` | `"unassigned"` | `"none"`) to each returned student.
- Keep existing phone masking and `requireAdmin` auth unchanged.

### 2. `public/admin.html` — column, filter, export (`loadStudents`)
- Add a **Group** column rendered as a colored badge, styled consistently with the
  existing `pref-badge`.
- Add a **filter dropdown** above the table: All / Group 1 / Group 2 / Unassigned / N/A.
  Filtering is client-side over the already-loaded data (instant).
- Add an **Export CSV** button that downloads the *currently-filtered* rows as CSV
  (columns: Email, Name, Group), generated client-side — no new endpoint. To get the
  un-registered email list, filter to **N/A** and export.
- Apply `escHtml()` to interpolated student values (current code omits it, unlike the
  other tables) while touching this render code.

## Out of scope
- No email-sending logic. The export gives the admin the list to email manually.

## Testing
- Verify the join in the browser: a student who is in `study_participants` with group 1/2
  shows the right label; one consented-but-unassigned shows Unassigned; one absent shows N/A.
- Verify filter narrows the table and Export downloads a CSV matching the filtered rows.
