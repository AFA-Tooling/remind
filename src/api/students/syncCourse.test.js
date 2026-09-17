import test from 'node:test';
import assert from 'node:assert/strict';

import { syncStudentCourseFromRoster } from './syncCourse.js';

/** Minimal in-memory Firestore covering just what syncStudentCourseFromRoster touches. */
function makeDb(seed = {}) {
  const data = new Map();
  for (const [collection, docs] of Object.entries(seed)) {
    for (const [id, value] of Object.entries(docs)) data.set(`${collection}/${id}`, value);
  }
  return {
    _data: data,
    collection(collection) {
      return {
        doc(id) {
          const key = `${collection}/${id}`;
          return {
            async get() {
              return { exists: data.has(key), data: () => data.get(key) };
            },
            async set(value, options) {
              data.set(key, options?.merge ? { ...(data.get(key) || {}), ...value } : value);
            },
          };
        },
      };
    },
  };
}

test('updates course_code when the roster disagrees', async () => {
  const db = makeDb({
    class_roster: { 's@berkeley.edu': { course_code: 'CS61C' } },
    students: { 's@berkeley.edu': { course_code: 'CS61A', category_prefs: {} } },
  });
  const result = await syncStudentCourseFromRoster(db, 's@berkeley.edu');
  assert.equal(result.patched, true);
  assert.equal(result.courseCode, 'CS61C');
  assert.equal(db._data.get('students/s@berkeley.edu').course_code, 'CS61C');
});

test('a pinned student is left alone even when the roster disagrees', async () => {
  // Regression coverage: this is the live, on-request path (settings page
  // load/save, the "Refresh from roster" button, sign-up) — separate from
  // the Python daily sync's own pin check. A student genuinely on more than
  // one course's real roster (class_roster only holds one course per email)
  // would otherwise get silently flipped back the moment they load or save
  // their own settings, undoing an admin's pin within seconds.
  const db = makeDb({
    class_roster: { 's@berkeley.edu': { course_code: 'CS61C' } },
    students: { 's@berkeley.edu': { course_code: 'CS61A', course_code_pinned: true, category_prefs: {} } },
  });
  const result = await syncStudentCourseFromRoster(db, 's@berkeley.edu');
  assert.equal(result.patched, false);
  assert.equal(result.courseCode, 'CS61A');
  assert.equal(db._data.get('students/s@berkeley.edu').course_code, 'CS61A', 'must not be overwritten');
});

test('an unpinned student still updates normally', async () => {
  const db = makeDb({
    class_roster: { 's@berkeley.edu': { course_code: 'CS61C' } },
    students: { 's@berkeley.edu': { course_code: 'CS61A', course_code_pinned: false, category_prefs: {} } },
  });
  const result = await syncStudentCourseFromRoster(db, 's@berkeley.edu');
  assert.equal(result.patched, true);
  assert.equal(result.courseCode, 'CS61C');
});

test('a student not on any roster is left alone regardless of the pin', async () => {
  const db = makeDb({
    students: { 's@berkeley.edu': { course_code: 'CS61A', category_prefs: {} } },
  });
  const result = await syncStudentCourseFromRoster(db, 's@berkeley.edu');
  assert.equal(result.patched, false);
  assert.equal(result.onRoster, false);
  assert.equal(result.courseCode, 'CS61A');
});
