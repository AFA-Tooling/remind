/**
 * Per-course config loader (mirrors services/shared/courses.py).
 * Source of truth: services/shared/courses.json
 */

import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const COURSES_JSON = path.join(__dirname, '../../services/shared/courses.json');

let cached = null;

export function loadCoursesConfig() {
  if (!cached) {
    cached = JSON.parse(fs.readFileSync(COURSES_JSON, 'utf-8'));
  }
  return cached;
}

/** Reset cache — for tests only. */
export function _resetCoursesCache() {
  cached = null;
}

export function defaultCourseCode() {
  return loadCoursesConfig().default_course_code || 'CS61A';
}

export function listCourseCodes() {
  return Object.keys(loadCoursesConfig().courses || {}).sort();
}

export function getCourse(courseCode) {
  const code = String(courseCode || '').trim().toUpperCase();
  if (!code) return null;
  return loadCoursesConfig().courses?.[code] || null;
}

export function defaultCategoryPrefs(courseCode) {
  const course = getCourse(courseCode) || getCourse(defaultCourseCode()) || {};
  const prefs = {};
  for (const cat of course.categories || []) {
    const id = String(cat.id || '').trim().toLowerCase();
    if (id) prefs[id] = true;
  }
  return prefs;
}

/**
 * Merge saved prefs onto the course's category set.
 * Unknown keys from an old course are dropped; new categories default to on.
 */
export function mergeCategoryPrefs(courseCode, existingPrefs) {
  const defaults = defaultCategoryPrefs(courseCode);
  const saved = existingPrefs && typeof existingPrefs === 'object' ? existingPrefs : {};
  const merged = {};
  for (const id of Object.keys(defaults)) {
    merged[id] = saved[id] !== false;
  }
  return merged;
}

/**
 * Keep only category keys that belong to the course.
 */
export function sanitizeCategoryPrefs(courseCode, incoming) {
  const defaults = defaultCategoryPrefs(courseCode);
  const src = incoming && typeof incoming === 'object' ? incoming : {};
  const out = {};
  for (const id of Object.keys(defaults)) {
    out[id] = !!src[id];
  }
  return out;
}

// Extra reminder days from the dashboard's "Advanced options" grid. The slider
// (days_before_deadline) is the main reminder; these only add days on top of it.
// Mirrors EXTRA_REMINDER_DAYS_FIELD / OTHER_REMINDER_KEY / MAX_REMINDER_DAYS in
// services/gradesync_input/db_fetch.py — keep the two in sync.
export const OTHER_REMINDER_KEY = 'other';
export const MAX_REMINDER_DAYS = 5;

/**
 * Clean an incoming extra_reminder_days object before saving.
 *
 * Keeps only the course's own category ids plus "other" (bCourses / uncategorized),
 * and only whole days in 0..MAX_REMINDER_DAYS, de-duplicated and sorted
 * high-to-low. Students with no known course get only the "other" row. Every
 * allowed row is present in the result, as [] when it has no extras.
 *
 * The slider day is deliberately NOT removed: extras are stored independently of
 * the slider, so a ticked extra survives the slider moving onto it and back off.
 * The daily job collapses an extra that equals the slider day into one reminder.
 *
 * Returns null when the input isn't a plain object, so callers can skip the write.
 */
export function sanitizeExtraReminderDays(courseCode, incoming) {
  if (!incoming || typeof incoming !== 'object' || Array.isArray(incoming)) {
    return null;
  }
  const course = getCourse(courseCode);
  const allowed = new Set([OTHER_REMINDER_KEY]);
  for (const cat of course?.categories || []) {
    const id = String(cat.id || '').trim().toLowerCase();
    if (id) allowed.add(id);
  }

  const out = {};
  for (const id of allowed) {
    const days = Array.isArray(incoming[id]) ? incoming[id] : [];
    const clean = [...new Set(
      days.filter((d) => Number.isInteger(d) && d >= 0 && d <= MAX_REMINDER_DAYS),
    )].sort((a, b) => b - a);
    // Every allowed row is written, empty or not: settings.js saves with
    // set({merge: true}), which merges nested maps key-by-key, so a row left
    // out here would keep its old stored value instead of being cleared.
    out[id] = clean;
  }
  return out;
}

export function publicCourseConfig(courseCode) {
  const course = getCourse(courseCode);
  if (!course) return null;
  const features = course.features || {};
  const projectEarly = features.project_early_reminder || {};
  const release = features.release_reminder || {};
  return {
    course_code: String(courseCode || '').trim().toUpperCase(),
    display_name: course.display_name || courseCode,
    categories: (course.categories || [])
      .filter((c) => c.id)
      .map((c) => ({
        id: c.id,
        label: c.label || c.name || c.id,
      })),
    features: {
      project_early_reminder: {
        enabled: !!projectEarly.enabled,
        ui_label:
          projectEarly.ui_label ||
          'Remind me a day earlier for projects',
      },
      release_reminder: {
        enabled: !!release.enabled,
        ui_label:
          release.ui_label || 'Notify me when a new assignment is released',
      },
    },
  };
}
