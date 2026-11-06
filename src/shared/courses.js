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

// ---------------------------------------------------------------------------
// Reading a student's courses and per-course prefs.
//
// Student docs are moving from one course per student to several:
//
//   old shape:  course_code: "CS61A"
//               category_prefs: {...}, project_early_reminder, release_reminder
//   new shape:  course_codes: ["CS61A", "CS61C"]
//               course_prefs: { CS61A: { category_prefs, project_early_reminder,
//                                        release_reminder }, ... }
//
// Production holds the old shape until the migration runs, and a mix of both
// while it runs. Every reader goes through these helpers, which accept both, so
// new code can deploy before the migration and survive a rollback. Once
// production is fully migrated, the old-shape branches can be deleted.
// Mirrors services/shared/courses.py — keep the two in sync.
// ---------------------------------------------------------------------------

function normalizeCode(code) {
  return String(code || '').trim().toUpperCase();
}

/**
 * Every course the student is enrolled in, normalized and de-duplicated.
 * The new `course_codes` list wins whenever it exists, even if empty, so a
 * stale legacy `course_code` can't re-enroll a student removed from every
 * course. Without the list, falls back to the legacy single `course_code`.
 */
export function studentCourseCodes(student) {
  const s = student || {};
  const codes = Array.isArray(s.course_codes) ? s.course_codes : [s.course_code];
  const result = [];
  for (const code of codes) {
    const normalized = normalizeCode(code);
    if (normalized && !result.includes(normalized)) result.push(normalized);
  }
  return result;
}

/**
 * Prefs for a course the student has never customized: every category on,
 * release reminders on (opt-out), project early reminder off (opt-in).
 */
export function defaultCoursePrefs(courseCode) {
  return {
    category_prefs: defaultCategoryPrefs(courseCode),
    project_early_reminder: false,
    release_reminder: true,
  };
}

/**
 * The student's prefs for one course, always in the full new shape.
 * Reads `course_prefs[courseCode]` (new shape) if present, otherwise the legacy
 * top-level fields if that course is the student's legacy `course_code`,
 * otherwise the defaults.
 */
export function studentCoursePrefs(student, courseCode) {
  const s = student || {};
  const code = normalizeCode(courseCode);
  let source = null;

  const entry = s.course_prefs && typeof s.course_prefs === 'object' ? s.course_prefs[code] : null;
  if (entry && typeof entry === 'object') {
    source = entry;
  } else if (code && normalizeCode(s.course_code) === code) {
    source = s; // legacy top-level fields
  }

  if (!source) return defaultCoursePrefs(code);

  return {
    category_prefs: mergeCategoryPrefs(code, source.category_prefs),
    project_early_reminder: source.project_early_reminder === true,
    release_reminder: source.release_reminder !== false,
  };
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
