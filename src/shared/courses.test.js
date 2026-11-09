import test from 'node:test';
import assert from 'node:assert/strict';

import {
  defaultCourseCode,
  defaultCategoryPrefs,
  publicCourseConfig,
  sanitizeCategoryPrefs,
  sanitizeExtraReminderDays,
  mergeCategoryPrefs,
  listCourseCodes,
} from './courses.js';

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

// --- sanitizeExtraReminderDays ----------------------------------------------

const EMPTY_CS61A_EXTRAS = {
  other: [], lab: [], homework: [], midterm: [], quiz: [], project: [],
};

test('extra reminder days: keeps valid days for course types and other', () => {
  assert.deepEqual(
    sanitizeExtraReminderDays('CS61A', { project: [1], other: [0] }),
    { ...EMPTY_CS61A_EXTRAS, project: [1], other: [0] },
  );
});

test('extra reminder days: every row is written, empty when unset', () => {
  // set({merge:true}) merges nested maps, so cleared rows must be sent as [].
  assert.deepEqual(sanitizeExtraReminderDays('CS61A', {}), EMPTY_CS61A_EXTRAS);
});

test('extra reminder days: drops bad values, dedupes, sorts high to low', () => {
  const out = sanitizeExtraReminderDays('CS61A', {
    project: [1, 3, 1, 0, 6, -1, 2.5, '2', true, null],
  });
  assert.deepEqual(out.project, [3, 1, 0]);
});

test('extra reminder days: drops types that are not in the course', () => {
  const out = sanitizeExtraReminderDays('CS61A', { postterm: [1], made_up: [2] });
  assert.equal('postterm' in out, false);
  assert.equal('made_up' in out, false);
});

test('extra reminder days: non-array row is treated as empty', () => {
  assert.deepEqual(sanitizeExtraReminderDays('CS61A', { project: 1 }).project, []);
});

test('extra reminder days: unknown course only gets the other row', () => {
  assert.deepEqual(
    sanitizeExtraReminderDays('NOPE', { project: [1], other: [2] }),
    { other: [2] },
  );
  assert.deepEqual(sanitizeExtraReminderDays(null, { other: [2] }), { other: [2] });
});

test('extra reminder days: uses each course\'s own types', () => {
  const out = sanitizeExtraReminderDays('CS10', { postterm: [1], lab: [2] });
  assert.deepEqual(out.postterm, [1]);
  assert.equal('lab' in out, false);
});

test('extra reminder days: non-object input returns null', () => {
  assert.equal(sanitizeExtraReminderDays('CS61A', null), null);
  assert.equal(sanitizeExtraReminderDays('CS61A', [1, 2]), null);
  assert.equal(sanitizeExtraReminderDays('CS61A', 'project'), null);
});
