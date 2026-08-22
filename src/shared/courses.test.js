import test from 'node:test';
import assert from 'node:assert/strict';

import {
  defaultCourseCode,
  defaultCategoryPrefs,
  publicCourseConfig,
  sanitizeCategoryPrefs,
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
