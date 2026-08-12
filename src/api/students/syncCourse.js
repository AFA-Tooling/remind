/**
 * Keep students.course_code in sync with class_roster.
 * Roster is authoritative when the student appears on it.
 */

import {
  defaultCategoryPrefs,
  mergeCategoryPrefs,
} from '../../shared/courses.js';

/**
 * @param {FirebaseFirestore.Firestore} db
 * @param {string} email login email (doc id in students)
 * @param {object} [existingData] already-loaded student data, if any
 * @returns {Promise<{ data: object, patched: boolean, onRoster: boolean, courseCode: string|null }>}
 */
export async function syncStudentCourseFromRoster(db, email, existingData = null) {
  const loginEmail = String(email || '').trim();
  const rosterKey = loginEmail.toLowerCase();

  const rosterSnap = await db.collection('class_roster').doc(rosterKey).get();
  const onRoster = rosterSnap.exists;
  const rosterCourse = onRoster
    ? String(rosterSnap.data()?.course_code || '').trim()
    : '';

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
      courseCode: rosterCourse || null,
    };
  }

  if (!onRoster || !rosterCourse) {
    return {
      data,
      patched: false,
      onRoster,
      courseCode: data.course_code || null,
    };
  }

  const current = String(data.course_code || '').trim();
  if (current === rosterCourse) {
    return {
      data,
      patched: false,
      onRoster: true,
      courseCode: rosterCourse,
    };
  }

  const patch = {
    course_code: rosterCourse,
    category_prefs: mergeCategoryPrefs(rosterCourse, data.category_prefs),
    updated_at: new Date().toISOString(),
  };
  await studentRef.set(patch, { merge: true });
  const next = { ...data, ...patch };
  return {
    data: next,
    patched: true,
    onRoster: true,
    courseCode: rosterCourse,
  };
}

export function prefsForResponse(courseCode, categoryPrefs) {
  return mergeCategoryPrefs(courseCode || undefined, categoryPrefs);
}

export { defaultCategoryPrefs };
