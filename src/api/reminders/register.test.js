import test from 'node:test';
import assert from 'node:assert/strict';

import { DEFAULT_COURSE_CODE, resolveCourseCode, buildNewStudent } from './register.js';

// Registration used to create student docs with no course_code at all. The daily
// pipeline routes each student to an assignment catalog by that field, so every
// self-registered student matched nothing and silently received no reminders.

test('resolveCourseCode prefers the roster entry', () => {
  assert.equal(resolveCourseCode({ course_code: 'CS61A' }), 'CS61A');
});

test('resolveCourseCode falls back to the default when the student is not on the roster', () => {
  assert.equal(resolveCourseCode(null), DEFAULT_COURSE_CODE);
});

test('resolveCourseCode falls back when the roster entry has no course_code', () => {
  assert.equal(resolveCourseCode({ email: 'a@berkeley.edu' }), DEFAULT_COURSE_CODE);
});

test('new student doc carries a course_code so the pipeline can route it', () => {
  const student = buildNewStudent({
    email: 'student@berkeley.edu',
    displayName: 'Jo Student',
    courseCode: 'CS61A',
  });
  assert.equal(student.course_code, 'CS61A');
});

test('new student doc keeps the existing default preferences', () => {
  const student = buildNewStudent({
    email: 'student@berkeley.edu',
    displayName: 'Jo Student',
    courseCode: 'CS61A',
  });
  assert.equal(student.email, 'student@berkeley.edu');
  assert.equal(student.preferred_first_name, 'Jo');
  assert.equal(student.days_before_deadline, 1);
  assert.equal(student.release_reminder, true);
});
