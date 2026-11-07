/**
 * Keep a student's courses (course_codes, plus the legacy course_code) in sync
 * with class_roster. Roster is authoritative when the student appears on it.
 * Mirrors decide_student_course_update in
 * services/gradesync_input/sync_student_courses.py — keep the two in sync.
 */

import {
  defaultCategoryPrefs,
  getCourse,
  mergeCategoryPrefs,
  studentCourseCodes,
} from '../../shared/courses.js';

function pickLegacyCode(current, codes) {
  const normalized = String(current || '').trim().toUpperCase();
  if (codes.includes(normalized)) return normalized;
  return codes[0] || '';
}

function sameList(a, b) {
  return Array.isArray(a) && a.length === b.length && a.every((v, i) => v === b[i]);
}

/**
 * Fields to merge into the student doc, or null if it already matches.
 * course_codes must equal the roster's; course_code stays put if it's one of
 * them, else moves to the first (reshaping the legacy category_prefs with it).
 * Pinned students are never touched.
 */
export function decideStudentCourseUpdate(student, rosterCodes) {
  if (!student || student.course_code_pinned) return null;
  const codes = studentCourseCodes({ course_codes: rosterCodes || [] });
  if (!codes.length) return null;

  const patch = {};
  if (!sameList(student.course_codes, codes)) patch.course_codes = codes;

  const legacy = pickLegacyCode(student.course_code, codes);
  if (String(student.course_code || '').trim() !== legacy) {
    patch.course_code = legacy;
    if (getCourse(legacy)) {
      patch.category_prefs = mergeCategoryPrefs(legacy, student.category_prefs);
    }
  }

  if (!Object.keys(patch).length) return null;
  patch.updated_at = new Date().toISOString();
  return patch;
}

/**
 * @param {FirebaseFirestore.Firestore} db
 * @param {string} email login email (doc id in students)
 * @param {object} [existingData] already-loaded student data, if any
 * @returns {Promise<{ data: object, patched: boolean, onRoster: boolean,
 *   courseCode: string|null, courseCodes: string[] }>}
 *   courseCode is the legacy single course; courseCodes is every course.
 */
export async function syncStudentCourseFromRoster(db, email, existingData = null) {
  const loginEmail = String(email || '').trim();
  const rosterKey = loginEmail.toLowerCase();

  const rosterSnap = await db.collection('class_roster').doc(rosterKey).get();
  const onRoster = rosterSnap.exists;
  const rosterCodes = onRoster ? studentCourseCodes(rosterSnap.data()) : [];

  const studentRef = db.collection('students').doc(loginEmail);
  let data = existingData;
  if (!data) {
    const snap = await studentRef.get();
    data = snap.exists ? snap.data() : null;
  }

  if (!data) {
    return {
      data: null,
      patched: false,
      onRoster,
      courseCode: rosterCodes[0] || null,
      courseCodes: rosterCodes,
    };
  }

  // A pinned student is never touched by roster sync — without this, a
  // student would get flipped back the moment they load or save their own
  // settings page, undoing an admin's pin within seconds rather than a day.
  const patch = onRoster ? decideStudentCourseUpdate(data, rosterCodes) : null;
  if (!patch) {
    return {
      data,
      patched: false,
      onRoster,
      courseCode: data.course_code || null,
      courseCodes: studentCourseCodes(data),
    };
  }

  await studentRef.set(patch, { merge: true });
  const next = { ...data, ...patch };
  return {
    data: next,
    patched: true,
    onRoster: true,
    courseCode: next.course_code || null,
    courseCodes: studentCourseCodes(next),
  };
}

export function prefsForResponse(courseCode, categoryPrefs) {
  return mergeCategoryPrefs(courseCode || undefined, categoryPrefs);
}

export { defaultCategoryPrefs };
