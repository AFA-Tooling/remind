import test from 'node:test';
import assert from 'node:assert/strict';

import {
  DEFAULT_COURSE_CODE,
  DEFAULT_DAYS_BEFORE_DEADLINE,
  resolveCourseCode,
  buildNewStudent,
} from './defaults.js';

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

// The study requires that consenting alone is enough to receive email reminders,
// so the channel defaults are opt-out rather than opt-in.
test('new student doc has email enabled by default', () => {
  const student = buildNewStudent({
    email: 'student@berkeley.edu',
    displayName: 'Jo Student',
    courseCode: 'CS61A',
  });
  assert.equal(student.email, 'student@berkeley.edu');
  assert.equal(student.preferred_first_name, 'Jo');
  assert.equal(student.email_pref, true);
  assert.equal(student.days_before_deadline, DEFAULT_DAYS_BEFORE_DEADLINE);
  assert.equal(student.release_reminder, true);
});

// Channels that need a target the student has not supplied must stay off, or the
// pipeline would try to route to a null phone number / Discord id.
test('new student doc leaves SMS and Discord off with no targets', () => {
  const student = buildNewStudent({ email: 'a@berkeley.edu', courseCode: 'CS61A' });
  assert.equal(student.phone_pref, false);
  assert.equal(student.discord_pref, false);
  assert.equal(student.phone_number, null);
  assert.equal(student.discord_id, null);
});

test('new student doc enables every assignment category', () => {
  const student = buildNewStudent({ email: 'a@berkeley.edu', courseCode: 'CS61A' });
  assert.deepEqual(student.category_prefs, {
    lab: true,
    homework: true,
    midterm: true,
    quiz: true,
    project: true,
  });
});

// The backfill distinguishes "never opened the settings page" from "explicitly
// turned email off" by comparing these two timestamps, so creation must set them
// to the same value.
test('new student doc stamps created_at and updated_at identically', () => {
  const student = buildNewStudent({ email: 'a@berkeley.edu', courseCode: 'CS61A' });
  assert.equal(student.created_at, student.updated_at);
});

test('enrolled_via records provenance and defaults to signup', () => {
  assert.equal(buildNewStudent({ email: 'a@b.edu', courseCode: 'CS61A' }).enrolled_via, 'signup');
  assert.equal(
    buildNewStudent({ email: 'a@b.edu', courseCode: 'CS61A', enrolledVia: 'consent' }).enrolled_via,
    'consent',
  );
});

test('a missing display name leaves preferred_first_name null rather than crashing', () => {
  const student = buildNewStudent({ email: 'a@berkeley.edu', courseCode: 'CS61A' });
  assert.equal(student.preferred_first_name, null);
});
