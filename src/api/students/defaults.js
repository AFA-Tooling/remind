// The shape of a freshly-created `students` document.
//
// Two paths create student docs and they must agree: consent-time enrollment
// (admin/study.js) and first sign-in (reminders/register.js). The study requires
// that consenting alone is enough to receive email reminders, so the defaults
// here are opt-out, not opt-in.
//
// services/gradesync_input/backfill_consent_enrollment.py mirrors this shape for
// the one-time backfill of already-consented students. Keep the two in sync.

// The daily pipeline routes each student to an assignment catalog by course_code.
// A student doc without it matches no catalog and silently receives nothing, so
// every creation path must set one.
export const DEFAULT_COURSE_CODE = process.env.COURSE_CODE || 'CS61A';

// Reminders fire on an exact match against this many days before the deadline,
// not across a window — a student gets one email per assignment at T-3.
export const DEFAULT_DAYS_BEFORE_DEADLINE = 3;

// Functionally identical to omitting the field (db_fetch.py treats a missing
// category as enabled), but written explicitly so the dashboard renders the
// boxes checked rather than inferring them.
export function defaultCategoryPrefs() {
  return { lab: true, homework: true, midterm: true, quiz: true, project: true };
}

// The class roster is authoritative; students who registered but are not on it
// (staff, late adds) still need a course to be reachable.
export function resolveCourseCode(rosterEntry) {
  return rosterEntry?.course_code || DEFAULT_COURSE_CODE;
}

/**
 * Build a new student document.
 *
 * @param {object}  args
 * @param {string}  args.email        document id and contact address
 * @param {string} [args.displayName] full name, from the auth profile or roster
 * @param {string}  args.courseCode   already resolved via resolveCourseCode
 * @param {'consent'|'signup'} [args.enrolledVia] provenance, for study analysis
 */
export function buildNewStudent({ email, displayName, courseCode, enrolledVia = 'signup' }) {
  const now = new Date().toISOString();
  return {
    email,
    preferred_first_name: displayName ? displayName.split(' ')[0] : null,
    course_code: courseCode,
    phone_number: null,
    discord_id: null,
    days_before_deadline: DEFAULT_DAYS_BEFORE_DEADLINE,
    release_reminder: true,
    project_early_reminder: false,
    category_prefs: defaultCategoryPrefs(),
    email_pref: true,
    phone_pref: false,
    discord_pref: false,
    enrolled_via: enrolledVia,
    created_at: now,
    updated_at: now,
  };
}
