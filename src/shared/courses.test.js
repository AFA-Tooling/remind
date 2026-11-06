import test from 'node:test';
import assert from 'node:assert/strict';

import {
  defaultCourseCode,
  defaultCategoryPrefs,
  publicCourseConfig,
  sanitizeCategoryPrefs,
  mergeCategoryPrefs,
  listCourseCodes,
  studentCourseCodes,
  studentCoursePrefs,
  defaultCoursePrefs,
} from './courses.js';

const ALL_ON_61A = { lab: true, homework: true, midterm: true, quiz: true, project: true };
const ALL_ON_61C = { lab: true, homework: true, project: true };

test('default course is CS61A', () => {
  assert.equal(defaultCourseCode(), 'CS61A');
});

test('listCourseCodes returns every configured course, sorted', () => {
  const codes = listCourseCodes();
  assert.ok(codes.includes('CS61A'));
  assert.deepEqual(codes, [...codes].sort());
});

test('default category prefs match legacy keys', () => {
  assert.deepEqual(defaultCategoryPrefs('CS61A'), {
    lab: true,
    homework: true,
    midterm: true,
    quiz: true,
    project: true,
  });
});

test('public course config exposes UI fields', () => {
  const cfg = publicCourseConfig('CS61A');
  assert.equal(cfg.course_code, 'CS61A');
  assert.equal(cfg.display_name, 'CS 61A');
  assert.equal(cfg.categories.length, 5);
  assert.equal(cfg.features.project_early_reminder.enabled, true);
  assert.equal(cfg.features.release_reminder.enabled, true);
});

test('sanitize drops unknown category keys', () => {
  assert.deepEqual(
    sanitizeCategoryPrefs('CS61A', { lab: false, homework: true, nonsense: true }),
    {
      lab: false,
      homework: true,
      midterm: false,
      quiz: false,
      project: false,
    },
  );
});

test('merge preserves known prefs and defaults new ones on', () => {
  assert.deepEqual(mergeCategoryPrefs('CS61A', { lab: false }), {
    lab: false,
    homework: true,
    midterm: true,
    quiz: true,
    project: true,
  });
});

// --- studentCourseCodes (mirrors test_courses.py) ---------------------------

test('course codes: legacy single course', () => {
  assert.deepEqual(studentCourseCodes({ course_code: 'CS61A' }), ['CS61A']);
});

test('course codes: new list is normalized and de-duplicated', () => {
  const student = { course_codes: [' cs61a', 'CS61A', 'CS61C', ''], course_code: 'CS10' };
  assert.deepEqual(studentCourseCodes(student), ['CS61A', 'CS61C']);
});

test('course codes: empty when the student has no course', () => {
  assert.deepEqual(studentCourseCodes({}), []);
  assert.deepEqual(studentCourseCodes({ course_code: '' }), []);
  assert.deepEqual(studentCourseCodes(null), []);
});

test('course codes: an empty list wins over a stale legacy field', () => {
  assert.deepEqual(studentCourseCodes({ course_codes: [], course_code: 'CS61A' }), []);
});

// --- studentCoursePrefs -----------------------------------------------------

test('prefs: legacy doc, for its own course', () => {
  const student = {
    course_code: 'CS61A',
    category_prefs: { lab: false },
    project_early_reminder: true,
    release_reminder: false,
  };
  assert.deepEqual(studentCoursePrefs(student, 'CS61A'), {
    category_prefs: { ...ALL_ON_61A, lab: false },
    project_early_reminder: true,
    release_reminder: false,
  });
});

test('prefs: legacy doc, for another course, are the defaults', () => {
  const student = { course_code: 'CS61A', category_prefs: { lab: false }, release_reminder: false };
  assert.deepEqual(studentCoursePrefs(student, 'CS61C'), defaultCoursePrefs('CS61C'));
});

test('prefs: new doc reads the per-course entry, not legacy fields', () => {
  const student = {
    course_code: 'CS61A',
    category_prefs: { lab: false }, // stale legacy value, must be ignored
    course_codes: ['CS61A', 'CS61C'],
    course_prefs: {
      CS61A: { category_prefs: { homework: false }, release_reminder: true },
      CS61C: { category_prefs: { project: false }, project_early_reminder: true },
    },
  };
  assert.deepEqual(studentCoursePrefs(student, 'CS61A').category_prefs, { ...ALL_ON_61A, homework: false });
  assert.deepEqual(studentCoursePrefs(student, 'cs61c'), {
    category_prefs: { ...ALL_ON_61C, project: false },
    project_early_reminder: true,
    release_reminder: true,
  });
});

test('prefs: mixed doc falls back to legacy fields for an unmigrated course', () => {
  const student = {
    course_code: 'CS61A',
    category_prefs: { lab: false },
    course_codes: ['CS61A', 'CS61C'],
    course_prefs: { CS61C: {} },
  };
  assert.equal(studentCoursePrefs(student, 'CS61A').category_prefs.lab, false);
});

test('prefs: missing fields follow the pipeline defaults', () => {
  assert.deepEqual(studentCoursePrefs({ course_prefs: { CS61C: {} } }, 'CS61C'), defaultCoursePrefs('CS61C'));
  assert.deepEqual(defaultCoursePrefs('CS61C'), {
    category_prefs: ALL_ON_61C,
    project_early_reminder: false,
    release_reminder: true,
  });
});
