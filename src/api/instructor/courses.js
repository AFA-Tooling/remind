import { spawn } from 'child_process';
import { randomUUID } from 'crypto';
import path from 'path';
import { fileURLToPath } from 'url';
import { getDb } from '../firestore.js';
import { verifyUserAuth } from '../auth/verifyUser.js';
import {
  DIFFERENT_DAYS_NOTE,
  combineSourceAssignments,
  dueDay,
  mergeDuplicateReviewItems,
  outsideTermChecker,
  publishedNameReasons,
  websiteItemsCoveredByGradescope,
  withWebsiteSource,
} from './combineSources.js';

// Legacy review notes, cleaned up when courses are listed.
const RETIRED_REASON = /^Same name as |^Due \d{4}-\d{2}-\d{2}, which is outside /;
const OLD_DISAGREEMENT_NOTE = /^Versions are due on different days \(.*\)\. Check the date\.$/;
const LISTED_DAYS_NOTE = /^Versions are due on different days \(.*\)\. Use Edit to choose the due date\.$/;

/** Merges staged versions of one deadline ("Lab 2: Code", "Lab 2: Conceptual") into one item. */
async function mergeStagedDuplicates(db, course, reviewDocs) {
  const docById = new Map(reviewDocs.map(doc => [String(doc.data().assignment_id), doc]));
  const upgraded = new Set();
  const items = reviewDocs.map(doc => {
    const { duplicate_of: _of, duplicate_group: _group, ...item } = doc.data();
    const reasons = (Array.isArray(item.review_reasons) ? item.review_reasons : [])
      .filter(reason => !RETIRED_REASON.test(reason))
      .map(reason => (LISTED_DAYS_NOTE.test(reason) ? DIFFERENT_DAYS_NOTE : reason));
    // Legacy items with only combined_titles: turn them into pickable versions.
    const titles = Array.isArray(item.combined_titles) ? item.combined_titles : [];
    if (titles.length > 1 && !(Array.isArray(item.merged_versions) && item.merged_versions.length)) {
      upgraded.add(String(item.assignment_id));
      item.merged_versions = titles.map(title => ({
        assignment_name: title,
        due: item.due || null,
        source: 'gradescope',
        html_url: item.html_url || '',
        resources: [],
      }));
    }
    // Legacy items that auto-picked a date: clear it so the instructor chooses.
    const oldPick = reasons.findIndex(reason => OLD_DISAGREEMENT_NOTE.test(reason));
    if (oldPick === -1) return { ...item, review_reasons: reasons };
    upgraded.add(String(item.assignment_id));
    return {
      ...item,
      due: null,
      review_reasons: reasons.map((reason, index) => (index === oldPick
        ? DIFFERENT_DAYS_NOTE
        : reason)),
    };
  });
  const { items: merged, mergedIds, removedIds } = mergeDuplicateReviewItems(
    items,
    outsideTermChecker(course.course_website_term || course.term, course.course_website_url),
  );
  if (!mergedIds.length && !upgraded.size) return merged;
  const mergedSet = new Set([...mergedIds, ...upgraded]);
  const writes = [
    ...merged.filter(item => mergedSet.has(String(item.assignment_id)))
      .map(item => batch => batch.set(docById.get(String(item.assignment_id)).ref, item)),
    ...removedIds.map(id => batch => batch.delete(docById.get(id).ref)),
  ];
  for (let offset = 0; offset < writes.length; offset += 400) {
    const batch = db.batch();
    for (const write of writes.slice(offset, offset + 400)) write(batch);
    await batch.commit();
  }
  return merged;
}

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const IMPORT_SCRIPT = path.resolve(__dirname, '../../../gradesync_input/course_import.py');
const WEBSITE_IMPORT_SCRIPT = path.resolve(__dirname, '../../../gradesync_input/website_import.py');
const MAX_OUTPUT_BYTES = 1024 * 1024;
const IMPORT_TIMEOUT_MS = 90 * 1000;
const WEBSITE_IMPORT_TIMEOUT_MS = 240 * 1000;

function parseCourseId(input) {
  const value = String(input || '').trim();
  return /^\d{1,20}$/.test(value) ? value : null;
}

function parseCourseWebsiteUrl(input) {
  const value = String(input || '').trim();
  if (!value) return '';
  if (value.length > 2048) return null;
  try {
    const url = new URL(value);
    if (!['http:', 'https:'].includes(url.protocol) || !url.hostname ||
        url.username || url.password) {
      return null;
    }
    return url.toString();
  } catch {
    return null;
  }
}

function parseAssignmentResources(input) {
  if (!Array.isArray(input) || input.length > 20) return null;
  const resources = [];
  for (const resource of input) {
    if (!resource || typeof resource !== 'object') return null;
    const resourceName = String(resource.resource_name || '').trim();
    const resourceType = String(resource.resource_type || '').trim() || 'Link';
    const link = String(resource.link || '').trim();
    if (!resourceName || resourceName.length > 120 ||
        !resourceType || resourceType.length > 40 ||
        link.length > 2048) {
      return null;
    }
    let url;
    try {
      url = new URL(link);
    } catch {
      return null;
    }
    if (!['http:', 'https:'].includes(url.protocol) || !url.hostname ||
        url.username || url.password) return null;
    resources.push({ resource_name: resourceName, resource_type: resourceType, link: url.toString() });
  }
  return resources;
}

function validWebsiteImport(imported) {
  if (!imported ||
      !Number.isInteger(imported.pages_crawled) ||
      imported.pages_crawled < 1 ||
      imported.pages_crawled > 180 ||
      !Number.isInteger(imported.candidates_reviewed) ||
      imported.candidates_reviewed < 0 ||
      imported.candidates_reviewed > 2000 ||
      (imported.pages_skipped !== undefined &&
        (!Number.isInteger(imported.pages_skipped) ||
          imported.pages_skipped < 0 ||
          imported.pages_skipped > 180)) ||
      typeof imported.course_url !== 'string' ||
      !imported.course_url.trim() ||
      !Array.isArray(imported.assignments)) {
    return false;
  }
  return imported.assignments.every(assignment =>
    assignment &&
    typeof assignment.id === 'string' &&
    /^[a-f0-9]{32}$/.test(assignment.id) &&
    typeof assignment.title === 'string' &&
    assignment.title.trim().length > 0 &&
    assignment.title.length <= 100 &&
    (assignment.due === null || /^\d{4}-\d{2}-\d{2}$/.test(assignment.due)) &&
    typeof assignment.html_url === 'string' &&
    assignment.html_url.trim().length > 0 &&
    assignment.html_url.length <= 2048 &&
    parseCourseWebsiteUrl(assignment.html_url) !== null &&
    assignment.source === 'website' &&
    parseAssignmentResources(assignment.resources) !== null
  );
}

const PROGRESS_PREFIX = '[progress] ';

/**
 * Splits an importer's stderr into progress steps (passed to onProgress as they
 * arrive) and everything else (kept for error messages and operator logs).
 */
function stderrReader(onProgress) {
  let partial = '';
  let other = '';
  const take = line => {
    if (line.startsWith(PROGRESS_PREFIX)) {
      const message = line.slice(PROGRESS_PREFIX.length).trim();
      if (message && onProgress) {
        try { onProgress(message.slice(0, 200)); } catch { /* progress is best effort */ }
      }
    } else {
      other += `${line}\n`;
    }
  };
  return {
    push(chunk) {
      partial += chunk.toString();
      const lines = partial.split('\n');
      partial = lines.pop();
      lines.forEach(take);
    },
    text() {
      if (partial) { take(partial); partial = ''; }
      return other;
    },
  };
}

function runGradescopeImport(courseId, onProgress) {
  return new Promise((resolve, reject) => {
    const child = spawn(
      process.env.PYTHON || 'python3',
      [IMPORT_SCRIPT, courseId],
      { env: process.env, stdio: ['ignore', 'pipe', 'pipe'] },
    );
    let stdout = '';
    const stderr = stderrReader(onProgress);
    let outputBytes = 0;
    let settled = false;

    const finish = (error, value) => {
      if (settled) return;
      settled = true;
      clearTimeout(timeout);
      if (error) reject(error);
      else resolve(value);
    };

    const timeout = setTimeout(() => {
      child.kill('SIGTERM');
      finish(new Error('Gradescope import timed out'));
    }, IMPORT_TIMEOUT_MS);

    child.stdout.on('data', chunk => {
      outputBytes += chunk.length;
      if (outputBytes > MAX_OUTPUT_BYTES) {
        child.kill('SIGTERM');
        finish(new Error('Gradescope returned too much data'));
        return;
      }
      stdout += chunk.toString();
    });
    child.stderr.on('data', chunk => stderr.push(chunk));
    child.on('error', error => finish(error));
    child.on('close', code => {
      if (settled) return;
      if (code !== 0) {
        finish(new Error(stderr.text().trim() || 'Gradescope import failed'));
        return;
      }
      try {
        const result = JSON.parse(stdout);
        if (!/^\d{1,20}$/.test(result.course_id) ||
            result.course_id !== courseId ||
            !Array.isArray(result.assignments)) {
          throw new Error('Gradescope returned an invalid course response');
        }
        finish(null, result);
      } catch (error) {
        finish(error);
      }
    });
  });
}

function runCourseWebsiteImport(courseUrl, term, onProgress) {
  return new Promise((resolve, reject) => {
    const child = spawn(
      process.env.PYTHON || 'python3',
      [WEBSITE_IMPORT_SCRIPT, courseUrl, term],
      { env: process.env, stdio: ['ignore', 'pipe', 'pipe'] },
    );
    let stdout = '';
    const stderr = stderrReader(onProgress);
    let outputBytes = 0;
    let settled = false;

    const finish = (error, value) => {
      if (settled) return;
      settled = true;
      clearTimeout(timeout);
      if (error) reject(error);
      else resolve(value);
    };

    const timeout = setTimeout(() => {
      child.kill('SIGTERM');
      finish(new Error('Course website import timed out'));
    }, WEBSITE_IMPORT_TIMEOUT_MS);

    child.stdout.on('data', chunk => {
      outputBytes += chunk.length;
      if (outputBytes > MAX_OUTPUT_BYTES) {
        child.kill('SIGTERM');
        finish(new Error('Course website returned too much data'));
        return;
      }
      stdout += chunk.toString();
    });
    child.stderr.on('data', chunk => stderr.push(chunk));
    child.on('error', error => finish(error));
    child.on('close', code => {
      if (settled) return;
      if (code !== 0) {
        finish(new Error(stderr.text().trim() || 'Course website import failed'));
        return;
      }
      // Importer diagnostics (what the model listed, dates verified) for operators.
      for (const line of stderr.text().split('\n')) {
        if (line.startsWith('[website import]')) console.log(line);
      }
      try {
        finish(null, JSON.parse(stdout));
      } catch (error) {
        finish(error);
      }
    });
  });
}

const SERVICE_UNAVAILABLE_MESSAGE = 'Course website syncing isn’t available right now. Please try again later.';
const GRADESCOPE_UNAVAILABLE_MESSAGE = 'AutoRemind couldn’t connect to Gradescope right now. Please try again later.';

/** Maps importer failures to instructor-facing errors (never exposes provider, config, or logs). */
function sourceSyncErrorResponse(res, error, { timeoutMessage, fallbackMessage }) {
  const message = String(error?.message || '');
  // Problems on AutoRemind's side that the instructor cannot fix.
  if (message.includes('GRADESCOPE_CONFIG_ERROR:') || message.includes('GRADESCOPE_AUTH_ERROR:')) {
    return res.status(503).json({ error: GRADESCOPE_UNAVAILABLE_MESSAGE });
  }
  if ([
    'WEBSITE_IMPORT_CONFIG_ERROR:',
    'WEBSITE_IMPORT_GROQ_AUTH_ERROR:',
    'WEBSITE_IMPORT_GROQ_MODEL_ERROR:',
    'WEBSITE_IMPORT_LLM_ERROR:',
    'WEBSITE_IMPORT_LLM_OUTPUT_LIMIT_ERROR:',
  ].some(marker => message.includes(marker)) ||
      message.includes('Course website importer returned an invalid response')) {
    return res.status(503).json({ error: SERVICE_UNAVAILABLE_MESSAGE });
  }
  // Temporarily busy.
  if (message.includes('WEBSITE_IMPORT_DAILY_QUOTA_ERROR:')) {
    const retryAfter = Number(message.match(/Retry after (\d+) seconds/i)?.[1]);
    const waitMinutes = Number.isFinite(retryAfter) ? Math.ceil(retryAfter / 60) : null;
    return res.status(429).json({
      error: waitMinutes && waitMinutes <= 120
        ? `Course website syncing is busy right now. Please try again in about ${waitMinutes} minutes.`
        : 'Course website syncing is busy right now. Please try again later today.',
    });
  }
  if (message.includes('WEBSITE_IMPORT_RATE_LIMIT_ERROR:')) {
    return res.status(429).json({ error: 'Course website syncing is busy right now. Please try again in a few minutes.' });
  }
  // Things the instructor can act on.
  if (message.includes('WEBSITE_IMPORT_PROMPT_SIZE_ERROR:') || message.includes('WEBSITE_CRAWL_LIMIT_ERROR:')) {
    return res.status(422).json({
      error: 'This course page has too much on it to sync. No assignments were imported. Try a more specific page, such as the course schedule or assignments page.',
    });
  }
  if (message.includes('WEBSITE_IMPORT_TIME_BUDGET_ERROR:')) {
    return res.status(504).json({
      error: 'This course page took too long to sync. No assignments were imported. Try a more specific page, such as the course schedule or assignments page.',
    });
  }
  if (message.includes('WEBSITE_FETCH_ERROR:')) {
    const fetchMessage = message.split('WEBSITE_FETCH_ERROR:').pop().trim();
    return res.status(502).json({
      error: `${fetchMessage} Check that the course website is public and the link is correct. No assignments were imported.`,
    });
  }
  if (message.includes('Could not resolve course website host:')) {
    return res.status(502).json({
      error: 'The course website couldn’t be found. Check that the link is correct.',
    });
  }
  if (message.includes('timed out')) {
    return res.status(504).json({ error: timeoutMessage });
  }
  return res.status(502).json({ error: fallbackMessage });
}

/** Fields recording which source assignments a combined item stands for. */
function combinedFields(assignment) {
  const ids = Array.isArray(assignment.source_ids) ? assignment.source_ids.map(String) : [];
  const titles = Array.isArray(assignment.combined_titles) ? assignment.combined_titles.map(String) : [];
  const versions = Array.isArray(assignment.merged_versions) ? assignment.merged_versions : [];
  return {
    ...(ids.length ? { source_ids: ids } : {}),
    ...(titles.length ? { combined_titles: titles } : {}),
    ...(versions.length ? { merged_versions: versions } : {}),
  };
}

/** The course (any instructor's) already using this Gradescope course, if any. */
async function courseUsingGradescopeId(db, gradescopeCourseId, exceptCourseDocId = null) {
  if (!gradescopeCourseId) return null;
  const snapshot = await db.collection('instructor_courses')
    .where('gradescope_course_id', '==', String(gradescopeCourseId))
    .get();
  return snapshot.docs.find(doc => doc.id !== exceptCourseDocId) || null;
}

// One message for everyone; it never reveals which course or instructor has the ID.
const GRADESCOPE_IN_USE_MESSAGE =
  'This Gradescope Course ID is already connected to a course in AutoRemind. If you think this is a mistake, please contact the AutoRemind team.';

function gradescopeInUseResponse(res) {
  return res.status(409).json({ error: GRADESCOPE_IN_USE_MESSAGE });
}

function assignmentDocumentId(uid, courseId, assignmentId) {
  return `${uid}__${courseId}__${assignmentId}`;
}

async function saveImportedCourse(db, uid, imported, metadata) {
  const courseId = metadata.course_key;
  const courseRef = db.collection('instructor_courses').doc(`${uid}__${courseId}`);
  const syncedAt = new Date().toISOString();
  const assignments = imported.assignments.map(assignment => ({
    docId: assignmentDocumentId(uid, courseId, assignment.id),
    data: {
      owner_uid: uid,
      course_id: courseId,
      gradescope_course_id: imported.course_id || null,
      assignment_id: String(assignment.id),
      assignment_name: assignment.title,
      due: assignment.due || null,
      html_url: assignment.html_url || '',
      source: assignment.source || 'gradescope',
      resources: Array.isArray(assignment.resources) ? assignment.resources : [],
      ...combinedFields(assignment),
      synced_at: syncedAt,
    },
  }));

  const existing = await db.collection('instructor_course_assignments')
    .where('owner_uid', '==', uid)
    .get();
  const currentIds = new Set(assignments.map(assignment => assignment.docId));
  const stale = existing.docs.filter(doc =>
    doc.data().course_id === courseId && !currentIds.has(doc.id)
  );

  for (let offset = 0; offset < assignments.length; offset += 400) {
    const batch = db.batch();
    for (const assignment of assignments.slice(offset, offset + 400)) {
      batch.set(db.collection('instructor_course_assignments').doc(assignment.docId), assignment.data);
    }
    await batch.commit();
  }
  for (let offset = 0; offset < stale.length; offset += 400) {
    const batch = db.batch();
    for (const doc of stale.slice(offset, offset + 400)) batch.delete(doc.ref);
    await batch.commit();
  }

  await courseRef.set({
    owner_uid: uid,
    course_id: courseId,
    gradescope_course_id: imported.course_id || null,
    course_name: metadata.course_name,
    term: metadata.term,
    archived: metadata.archived || false,
    gradescope_url: metadata.gradescope_url || imported.course_url || '',
    course_website_url: metadata.course_website_url,
    course_url: metadata.gradescope_url || imported.course_url || '',
    assignment_count: assignments.length,
    status: 'finalized',
    synced_at: syncedAt,
  }, { merge: true });

  return {
    course_id: courseId,
    gradescope_course_id: imported.course_id || null,
    course_name: metadata.course_name,
    term: metadata.term,
    archived: metadata.archived || false,
    gradescope_url: metadata.gradescope_url || imported.course_url || '',
    course_website_url: metadata.course_website_url,
    course_url: metadata.gradescope_url || imported.course_url || '',
    assignment_count: assignments.length,
    status: 'finalized',
    synced_at: syncedAt,
    assignments: assignments.map(assignment => assignment.data),
  };
}

async function stageImportedCourse(db, uid, imported, metadata) {
  const courseId = metadata.course_key;
  const courseRef = db.collection('instructor_courses').doc(`${uid}__${courseId}`);
  const stagedCollection = db.collection('instructor_course_assignment_reviews');
  const existing = await stagedCollection.where('owner_uid', '==', uid).get();
  const stale = existing.docs.filter(doc => doc.data().course_id === courseId);
  for (let offset = 0; offset < stale.length; offset += 400) {
    const batch = db.batch();
    for (const doc of stale.slice(offset, offset + 400)) batch.delete(doc.ref);
    await batch.commit();
  }

  const syncedAt = new Date().toISOString();
  const stagedAssignments = imported.assignments.map(assignment => ({
    docId: assignmentDocumentId(uid, courseId, assignment.id),
    data: {
      owner_uid: uid,
      course_id: courseId,
      assignment_id: String(assignment.id),
      assignment_name: assignment.title,
      due: assignment.due || null,
      html_url: assignment.html_url || '',
      source: assignment.source || 'gradescope',
      resources: Array.isArray(assignment.resources) ? assignment.resources : [],
      ...combinedFields(assignment),
      review_reasons: Array.isArray(assignment.review_reasons) ? assignment.review_reasons : [],
    },
  }));
  for (let offset = 0; offset < stagedAssignments.length; offset += 400) {
    const batch = db.batch();
    for (const assignment of stagedAssignments.slice(offset, offset + 400)) {
      batch.set(stagedCollection.doc(assignment.docId), assignment.data);
    }
    await batch.commit();
  }

  const course = {
    owner_uid: uid,
    course_id: courseId,
    gradescope_course_id: imported.course_id || null,
    course_name: metadata.course_name,
    term: metadata.term,
    archived: metadata.archived || false,
    gradescope_url: metadata.gradescope_url || imported.course_url || '',
    course_website_url: metadata.course_website_url,
    course_url: metadata.gradescope_url || imported.course_url || '',
    assignment_count: 0,
    pending_assignment_count: stagedAssignments.length,
    status: 'pending_review',
    synced_at: syncedAt,
    ...(metadata.course_website_synced_at ? {
      course_website_synced_at: metadata.course_website_synced_at,
      course_website_pages_crawled: metadata.course_website_pages_crawled,
      course_website_pages_skipped: metadata.course_website_pages_skipped,
      course_website_candidates_reviewed: metadata.course_website_candidates_reviewed,
      course_website_term: metadata.course_website_term || null,
    } : {}),
  };
  await courseRef.set(course, { merge: true });

  return { ...course, pending_assignments: stagedAssignments.map(assignment => assignment.data) };
}

/** Approved items by ID ("<id>" or "<merged id>#v<n>"); null if any ID is unknown. */
function approvedReviewItems(approvedIds, stagedById) {
  const items = [];
  for (const raw of new Set(approvedIds.map(String))) {
    const version = /^(.+)#v(\d+)$/.exec(raw);
    if (!version) {
      const doc = stagedById.get(raw);
      if (!doc) return null;
      items.push(doc.data());
      continue;
    }
    const parent = stagedById.get(version[1])?.data();
    const found = Array.isArray(parent?.merged_versions) ? parent.merged_versions[Number(version[2])] : null;
    if (!found) return null;
    items.push({
      owner_uid: parent.owner_uid,
      course_id: parent.course_id,
      assignment_id: `${version[1]}-v${version[2]}`,
      assignment_name: found.assignment_name,
      due: found.due || null,
      html_url: found.html_url || '',
      source: found.source || 'gradescope',
      resources: Array.isArray(found.resources) ? found.resources : [],
      review_reasons: [],
      ...(parent.synced_at ? { synced_at: parent.synced_at } : {}),
    });
  }
  return items;
}

async function finalizeReviewedCourse(db, uid, courseId, approvedAssignmentIds) {
  const courseSnapshot = await db.collection('instructor_courses')
    .where('owner_uid', '==', uid)
    .where('course_id', '==', courseId)
    .get();
  const courseDoc = courseSnapshot.docs[0];
  if (!courseDoc || courseDoc.data().status !== 'pending_review') {
    return null;
  }

  const stagedSnapshot = await db.collection('instructor_course_assignment_reviews')
    .where('owner_uid', '==', uid)
    .get();
  const stagedDocs = stagedSnapshot.docs.filter(doc => doc.data().course_id === courseId);
  const stagedById = new Map(stagedDocs.map(doc => [String(doc.data().assignment_id), doc]));
  const approvedItems = approvedReviewItems(approvedAssignmentIds, stagedById);
  if (!approvedItems) {
    throw new Error('Approved assignment list contains an unknown assignment');
  }
  // Every published deadline needs a due date.
  const undated = approvedItems.find(item => !item.due);
  if (undated) return { undated: undated.assignment_name };

  const currentCourse = courseDoc.data();
  const imported = {
    course_id: currentCourse.gradescope_course_id,
    course_url: currentCourse.gradescope_url,
    assignments: approvedItems.map(assignment => {
      return {
        id: assignment.assignment_id,
        title: assignment.assignment_name,
        due: assignment.due,
        html_url: assignment.html_url,
        source: assignment.source || 'gradescope',
        resources: Array.isArray(assignment.resources) ? assignment.resources : [],
        ...combinedFields(assignment),
      };
    }),
  };
  const metadata = {
    course_key: courseId,
    course_name: currentCourse.course_name,
    term: currentCourse.term || '',
    gradescope_url: currentCourse.gradescope_url || '',
    course_website_url: currentCourse.course_website_url || '',
    archived: Boolean(currentCourse.archived),
  };
  const finalized = await saveImportedCourse(db, uid, imported, metadata);
  const courseRef = db.collection('instructor_courses').doc(courseDoc.id);
  await courseRef.set({ pending_assignment_count: 0, status: 'finalized' }, { merge: true });

  for (let offset = 0; offset < stagedDocs.length; offset += 400) {
    const batch = db.batch();
    for (const doc of stagedDocs.slice(offset, offset + 400)) batch.delete(doc.ref);
    await batch.commit();
  }
  return { ...finalized, pending_assignment_count: 0, status: 'finalized' };
}

async function findOwnedCourse(db, uid, courseId) {
  const directDocRef = db.collection('instructor_courses').doc(`${uid}__${courseId}`);
  const directDoc = await directDocRef.get();
  if (directDoc.exists &&
      directDoc.data()?.owner_uid === uid &&
      directDoc.data()?.course_id === courseId) {
    return {
      id: directDoc.id || `${uid}__${courseId}`,
      ref: directDoc.ref || directDocRef,
      exists: true,
      data: () => directDoc.data(),
    };
  }
  const snapshot = await db.collection('instructor_courses')
    .where('owner_uid', '==', uid)
    .where('course_id', '==', courseId)
    .get();
  return snapshot.docs[0] || null;
}

async function addInstructorCourseAssignment(db, uid, courseId, assignmentName, due, resources = []) {
  const courseDoc = await findOwnedCourse(db, uid, courseId);
  if (!courseDoc) return null;

  const course = courseDoc.data();
  const assignmentId = `manual-${randomUUID()}`;
  const assignment = {
    owner_uid: uid,
    course_id: courseId,
    assignment_id: assignmentId,
    assignment_name: assignmentName,
    due: due || null,
    html_url: '',
    source: 'instructor',
    resources,
  };
  const pending = course.status === 'pending_review';
  const collection = pending
    ? 'instructor_course_assignment_reviews'
    : 'instructor_course_assignments';
  await db.collection(collection)
    .doc(assignmentDocumentId(uid, courseId, assignmentId))
    .set(assignment);

  const countField = pending ? 'pending_assignment_count' : 'assignment_count';
  const newCount = Math.max(0, Number(course[countField]) || 0) + 1;
  await db.collection('instructor_courses').doc(courseDoc.id).set({ [countField]: newCount }, { merge: true });
  return assignment;
}

async function findCourseAssignmentDoc(db, uid, courseId, collection, assignmentId) {
  const expectedDocId = assignmentDocumentId(uid, courseId, assignmentId);
  const directDocRef = db.collection(collection).doc(expectedDocId);
  const directDoc = await directDocRef.get();

  let assignmentDoc = null;
  if (directDoc.exists &&
      directDoc.data()?.owner_uid === uid &&
      directDoc.data()?.course_id === courseId &&
      String(directDoc.data()?.assignment_id) === assignmentId) {
    assignmentDoc = {
      id: directDoc.id || expectedDocId,
      ref: directDoc.ref || directDocRef,
      data: () => directDoc.data(),
    };
  } else {
    const snapshot = await db.collection(collection)
      .where('owner_uid', '==', uid)
      .get();
    assignmentDoc = snapshot.docs.find(doc =>
      doc.data().course_id === courseId && String(doc.data().assignment_id) === assignmentId
    );
  }
  return assignmentDoc;
}

/** "<merged item ID>#v<n>" names one version of a merged item. */
function parseVersionId(assignmentId) {
  const match = /^(.+)#v(\d+)$/.exec(assignmentId);
  return match ? { parentId: match[1], index: Number(match[2]) } : null;
}

async function removeInstructorCourseAssignment(db, uid, courseId, assignmentId) {
  const courseDoc = await findOwnedCourse(db, uid, courseId);
  if (!courseDoc) return null;

  const pending = courseDoc.data().status === 'pending_review';
  const collection = pending
    ? 'instructor_course_assignment_reviews'
    : 'instructor_course_assignments';

  const version = parseVersionId(assignmentId);
  const assignmentDoc = await findCourseAssignmentDoc(
    db, uid, courseId, collection, version ? version.parentId : assignmentId,
  );
  if (!assignmentDoc) return { course_id: courseId, removed: false };
  if (version) {
    const versions = assignmentDoc.data().merged_versions;
    if (!Array.isArray(versions) || !versions[version.index]) return { course_id: courseId, removed: false };
    await db.collection(collection).doc(assignmentDoc.id).set({
      merged_versions: versions.filter((_, index) => index !== version.index),
    }, { merge: true });
    return { course_id: courseId, removed: true };
  }

  await db.collection(collection).doc(assignmentDoc.id).delete();
  const course = courseDoc.data();
  const countField = pending ? 'pending_assignment_count' : 'assignment_count';
  const newCount = Math.max(0, (Number(course[countField]) || 0) - 1);
  await db.collection('instructor_courses').doc(courseDoc.id).set({ [countField]: newCount }, { merge: true });
  return { course_id: courseId, removed: true };
}

async function updateInstructorCourseAssignment(db, uid, courseId, assignmentId, updates, collectionOverride = null) {
  const courseDoc = await findOwnedCourse(db, uid, courseId);
  if (!courseDoc) return null;

  const pending = courseDoc.data().status === 'pending_review';
  const collection = collectionOverride || (pending
    ? 'instructor_course_assignment_reviews'
    : 'instructor_course_assignments');

  const version = parseVersionId(assignmentId);
  const assignmentDoc = await findCourseAssignmentDoc(
    db, uid, courseId, collection, version ? version.parentId : assignmentId,
  );
  if (!assignmentDoc) return { notFound: true };
  if (version) {
    const versions = assignmentDoc.data().merged_versions;
    if (!Array.isArray(versions) || !versions[version.index]) return { notFound: true };
    await db.collection(collection).doc(assignmentDoc.id).set({
      merged_versions: versions.map((item, index) => (index === version.index ? { ...item, ...updates } : item)),
      ...(collection === 'instructor_course_assignment_reviews' ? { instructor_edited: true } : {}),
    }, { merge: true });
    return { course_id: courseId, assignment_id: assignmentId };
  }

  // Editing an item under review is reviewing it: its notes no longer apply, and a
  // later sync keeps it as edited instead of replacing it.
  if (collection === 'instructor_course_assignment_reviews') {
    updates = { ...updates, review_reasons: [], instructor_edited: true };
  }
  await db.collection(collection).doc(assignmentDoc.id).set(updates, { merge: true });
  return { course_id: courseId, assignment_id: assignmentId };
}

async function reviewSyncedAssignments(db, uid, courseId, approvedIds) {
  const courseDoc = await findOwnedCourse(db, uid, courseId);
  if (!courseDoc) return null;
  const snapshot = await db.collection('instructor_course_assignment_reviews')
    .where('owner_uid', '==', uid)
    .get();
  const stagedDocs = snapshot.docs.filter(doc => doc.data().course_id === courseId);
  const stagedById = new Map(stagedDocs.map(doc => [String(doc.data().assignment_id), doc]));
  const approved = approvedReviewItems(approvedIds, stagedById);
  if (!approved) {
    return { invalid: true };
  }
  const undated = approved.find(item => !item.due);
  if (undated) return { undated: undated.assignment_name };

  const course = courseDoc.data();
  const assignmentCollection = 'instructor_course_assignments';
  if (course.status !== 'pending_review') {
    for (const assignment of approved) {
      await db.collection(assignmentCollection)
        .doc(assignmentDocumentId(uid, courseId, assignment.assignment_id))
        .set(assignment);
    }
    for (const doc of stagedDocs) await db.collection('instructor_course_assignment_reviews').doc(doc.id).delete();
    const newCount = Math.max(0, (Number(course.assignment_count) || 0) + approved.length);
    await db.collection('instructor_courses').doc(courseDoc.id).set({
      assignment_count: newCount,
      pending_assignment_count: 0,
    }, { merge: true });
    return { course_id: courseId, added_count: approved.length };
  }

  return { invalid: true };
}

/** Records the website as a second source on stored items it now also lists. */
async function recordWebsiteSources(courseDocs, importedAssignments, coveredWebsiteIds) {
  const docByAssignmentId = new Map(courseDocs.map(doc => [String(doc.data().assignment_id), doc]));
  const found = new Map(); // stored doc -> { versions, ids } the website adds
  const add = (assignmentId, versions, ids) => {
    const doc = docByAssignmentId.get(String(assignmentId));
    if (!doc || !versions.length) return;
    if (!found.has(doc)) found.set(doc, { versions: [], ids: [] });
    found.get(doc).versions.push(...versions);
    found.get(doc).ids.push(...ids);
  };
  for (const assignment of importedAssignments) {
    const id = String(assignment.id);
    if (assignment.source === 'website') {
      for (const coveringId of coveredWebsiteIds.get(id) || []) {
        add(coveringId, [{
          assignment_name: assignment.title,
          due: assignment.due || null,
          source: 'website',
          html_url: assignment.html_url || '',
          resources: Array.isArray(assignment.resources) ? assignment.resources : [],
        }], [id]);
      }
      continue;
    }
    const websiteVersions = (Array.isArray(assignment.merged_versions) ? assignment.merged_versions : [])
      .filter(version => version.source === 'website');
    const ids = Array.isArray(assignment.source_ids) ? assignment.source_ids.map(String) : [id];
    for (const sourceId of new Set([id, ...ids])) add(sourceId, websiteVersions, ids);
  }
  for (const [doc, { versions, ids }] of found) {
    const updates = withWebsiteSource(doc.data(), versions, ids);
    if (updates) await doc.ref.set(updates, { merge: true });
  }
}

/** The sources an item came from: its own and those of every version it stands for. */
function itemSources(item) {
  const versions = Array.isArray(item.merged_versions) ? item.merged_versions : [];
  return new Set([item.source || 'gradescope', ...versions.map(version => version.source || 'gradescope')]);
}

/**
 * Whether a sync of these sources replaces this review item with its fresh import.
 * Items the instructor added or edited are kept; so are items that also came from a
 * source this sync did not read (a Gradescope-only sync keeps website items).
 */
function replacedBySync(item, refreshSources) {
  if (!refreshSources.size || item.instructor_edited) return false;
  if (item.source === 'instructor' || String(item.assignment_id).startsWith('manual-')) return false;
  return [...itemSources(item)].every(source => refreshSources.has(source));
}

async function syncInstructorCourse(db, uid, courseDoc, metadata, imported, { refreshSources = [] } = {}) {
  const course = courseDoc.data();
  const courseId = course.course_id;
  const assignmentCollection = 'instructor_course_assignment_reviews';
  const [assignmentSnapshot, reviewSnapshot] = await Promise.all([
    db.collection('instructor_course_assignments').where('owner_uid', '==', uid).get(),
    db.collection('instructor_course_assignment_reviews').where('owner_uid', '==', uid).get(),
  ]);
  // Items still in review are re-read from their sources on every sync, so corrections
  // to the importers (a date fixed, two names found to be one item) reach them.
  // Published items are never changed here.
  const refresh = new Set(refreshSources);
  const courseReviewDocs = reviewSnapshot.docs.filter(doc => doc.data().course_id === courseId);
  const replacedDocs = courseReviewDocs.filter(doc => replacedBySync(doc.data(), refresh));
  // What was already waiting for review, by name and due day: a re-read item that
  // changed (a corrected date) is new to the instructor; an identical one is not.
  const reviewSignature = item => `${String(item.assignment_name || '').trim().toLowerCase()}|${dueDay(item.due) || ''}`;
  const replacedSignatures = new Set(replacedDocs.map(doc => reviewSignature(doc.data())));
  const keptReviewDocs = courseReviewDocs.filter(doc => !replacedDocs.includes(doc));
  const courseDocs = [
    ...assignmentSnapshot.docs.filter(doc => doc.data().course_id === courseId),
    ...keptReviewDocs,
  ];
  const existingCourseDocs = courseDocs.map(doc => doc.data());
  // Skip only exact ID matches; same-name items are still staged for review.
  const existingIds = new Set(existingCourseDocs.flatMap(data => [
    String(data.assignment_id),
    ...(Array.isArray(data.source_ids) ? data.source_ids.map(String) : []),
  ]));
  // Skip website items already covered by an existing Gradescope item.
  const coveredWebsiteIds = websiteItemsCoveredByGradescope(
    existingCourseDocs,
    imported.assignments.filter(assignment => assignment.source === 'website'),
  );
  const syncedAt = new Date().toISOString();
  await recordWebsiteSources(courseDocs, imported.assignments, coveredWebsiteIds);
  const incoming = imported.assignments
    .filter(assignment => !existingIds.has(String(assignment.id)))
    .filter(assignment => !coveredWebsiteIds.has(String(assignment.id)));
  const newAssignments = incoming
    .map(assignment => ({
      owner_uid: uid,
      course_id: courseId,
      assignment_id: String(assignment.id),
      assignment_name: assignment.title,
      due: assignment.due || null,
      html_url: assignment.html_url || '',
      source: assignment.source || 'gradescope',
      resources: Array.isArray(assignment.resources) ? assignment.resources : [],
      ...combinedFields(assignment),
      review_reasons: Array.isArray(assignment.review_reasons) ? assignment.review_reasons : [],
      synced_at: syncedAt,
    }));
  const written = new Set();
  for (const assignment of newAssignments) {
    const docId = assignmentDocumentId(uid, courseId, assignment.assignment_id);
    await db.collection(assignmentCollection).doc(docId).set(assignment);
    written.add(docId);
  }
  // Replaced items the fresh import no longer lists (or lists differently) go away.
  for (const doc of replacedDocs) {
    if (!written.has(doc.id)) await db.collection(assignmentCollection).doc(doc.id).delete();
  }
  const pendingCount = keptReviewDocs.length + newAssignments.length;
  const nextCourse = {
    ...metadata,
    gradescope_course_id: metadata.gradescope_course_id ?? imported.course_id ?? null,
    gradescope_url: metadata.gradescope_url || (imported.course_id ? imported.course_url || '' : ''),
    course_url: imported.course_url || metadata.course_url || metadata.gradescope_url || '',
    synced_at: syncedAt,
    pending_assignment_count: pendingCount,
  };
  await db.collection('instructor_courses').doc(courseDoc.id).set(nextCourse, { merge: true });
  return {
    ...course,
    ...nextCourse,
    new_assignments: newAssignments,
    // What this sync found that was not already waiting for review.
    newly_found_count: newAssignments.filter(item => !replacedSignatures.has(reviewSignature(item))).length,
  };
}

export async function listInstructorCourses(db, uid) {
  const courseSnapshot = await db.collection('instructor_courses')
    .where('owner_uid', '==', uid)
    .get();
  const assignmentSnapshot = await db.collection('instructor_course_assignments')
    .where('owner_uid', '==', uid)
    .get();
  const reviewSnapshot = await db.collection('instructor_course_assignment_reviews')
    .where('owner_uid', '==', uid)
    .get();

  const assignmentsByCourse = new Map();
  const groupAssignments = (docs, grouped) => {
    for (const doc of docs) {
      const assignment = doc.data();
      const list = grouped.get(assignment.course_id) || [];
      list.push(assignment);
      grouped.set(assignment.course_id, list);
    }
  };
  groupAssignments(assignmentSnapshot.docs, assignmentsByCourse);
  const reviewDocsByCourse = new Map();
  for (const doc of reviewSnapshot.docs) {
    const courseId = doc.data().course_id;
    if (!reviewDocsByCourse.has(courseId)) reviewDocsByCourse.set(courseId, []);
    reviewDocsByCourse.get(courseId).push(doc);
  }
  const pendingAssignmentsByCourse = new Map();
  const mergedCounts = new Map();
  for (const doc of courseSnapshot.docs) {
    const course = doc.data();
    const reviewDocs = reviewDocsByCourse.get(course.course_id);
    if (!reviewDocs?.length) continue;
    const merged = await mergeStagedDuplicates(db, course, reviewDocs);
    pendingAssignmentsByCourse.set(course.course_id, merged);
    if (merged.length !== reviewDocs.length) {
      await db.collection('instructor_courses').doc(doc.id)
        .set({ pending_assignment_count: merged.length }, { merge: true });
      mergedCounts.set(course.course_id, merged.length);
    }
  }

  const sortAssignments = assignments => assignments.sort((a, b) => {
    const dueOrder = !a.due
      ? (b.due ? 1 : 0)
      : !b.due
        ? -1
        : new Date(a.due) - new Date(b.due);
    return dueOrder || String(a.assignment_name || '').localeCompare(
      String(b.assignment_name || ''),
      undefined,
      { numeric: true, sensitivity: 'base' },
    );
  });

  return courseSnapshot.docs.map(doc => {
    const { description: _description, ...course } = doc.data();
    if (mergedCounts.has(course.course_id)) course.pending_assignment_count = mergedCounts.get(course.course_id);
    const pending = course.status === 'pending_review';
    const assignments = pending ? [] : sortAssignments(assignmentsByCourse.get(course.course_id) || []);
    const pendingAssignments = pending
      ? sortAssignments(pendingAssignmentsByCourse.get(course.course_id) || [])
      : [];
    const sameNames = publishedNameReasons(pendingAssignmentsByCourse.get(course.course_id) || [], assignments);
    const newAssignments = pending
      ? []
      : sortAssignments((pendingAssignmentsByCourse.get(course.course_id) || []).map(item => ({
        ...item,
        review_reasons: [...item.review_reasons, ...(sameNames.get(String(item.assignment_id)) || [])],
      })));
    return {
      ...course,
      archived: Boolean(course.archived),
      assignments,
      pending_assignments: pendingAssignments,
      new_assignments: newAssignments,
    };
  }).sort((a, b) => a.course_name.localeCompare(b.course_name));
}

async function deleteInstructorCourse(db, uid, courseId) {
  const courseDoc = await findOwnedCourse(db, uid, courseId);
  if (!courseDoc) return null;

  const assignmentCollections = [
    'instructor_course_assignments',
    'instructor_course_assignment_reviews',
  ];
  const relatedDocs = [];
  for (const collectionName of assignmentCollections) {
    const snapshot = await db.collection(collectionName)
      .where('owner_uid', '==', uid)
      .get();
    relatedDocs.push(...snapshot.docs.filter(doc => doc.data().course_id === courseId));
  }

  const docsToDelete = [...relatedDocs, courseDoc];
  for (let offset = 0; offset < docsToDelete.length; offset += 400) {
    const batch = db.batch();
    for (const doc of docsToDelete.slice(offset, offset + 400)) batch.delete(doc.ref);
    await batch.commit();
  }

  return { course_id: courseId, course_name: courseDoc.data().course_name };
}

async function setInstructorCourseArchived(db, uid, courseId, archived) {
  const courseDoc = await findOwnedCourse(db, uid, courseId);
  if (!courseDoc) return null;

  await db.collection('instructor_courses').doc(courseDoc.id).set({ archived }, { merge: true });
  return { ...courseDoc.data(), archived };
}

export default async function handler(req, res, deps = {}) {
  if (!['GET', 'POST', 'PUT', 'DELETE'].includes(req.method)) {
    return res.status(405).json({ error: 'Method not allowed' });
  }

  const verifyAuth = deps.verifyUserAuth || verifyUserAuth;
  const dbFactory = deps.getDb || getDb;
  const runImportCourse = deps.importCourse || runGradescopeImport;
  const runImportCourseWebsite = deps.importCourseWebsite || runCourseWebsiteImport;
  // When the client asked for a progress stream, res.progress relays each importer
  // step ({ source, message } or { source, done }) before the final response.
  const progress = event => {
    if (typeof res.progress !== 'function') return;
    try { res.progress(event); } catch { /* progress is best effort */ }
  };
  const importCourse = gradescopeCourseId =>
    runImportCourse(gradescopeCourseId, message => progress({ source: 'gradescope', message }))
      .then(result => { progress({ source: 'gradescope', done: true }); return result; });
  const importCourseWebsite = (courseWebsiteUrl, term) =>
    runImportCourseWebsite(courseWebsiteUrl, term, message => progress({ source: 'website', message }))
      .then(result => { progress({ source: 'website', done: true }); return result; });
  const savingProgress = () => progress({ source: 'save', message: 'Saving the course and its assignments' });
  const auth = await verifyAuth(req);
  if (!auth.authorized) {
    return res.status(401).json({ error: auth.error });
  }
  if (!auth.uid) {
    return res.status(401).json({ error: 'Authenticated user ID is missing' });
  }

  try {
    const db = dbFactory();
    const profile = await db.collection('user_profiles').doc(auth.uid).get();
    if (!profile.exists || profile.data()?.role !== 'instructor') {
      return res.status(403).json({ error: 'Instructor role required' });
    }

    if (req.method === 'GET') {
      const courses = await listInstructorCourses(db, auth.uid);
      return res.status(200).json({ success: true, courses });
    }

    let body;
    try {
      body = typeof req.body === 'string' ? JSON.parse(req.body || '{}') : req.body;
    } catch {
      return res.status(400).json({ error: 'Request body must be valid JSON' });
    }

    if (req.method === 'DELETE') {
      const courseId = String(body?.course_id || '').trim();
      if (!/^[A-Za-z0-9_-]{1,128}$/.test(courseId)) {
        return res.status(400).json({ error: 'A valid course ID is required to delete a course.' });
      }
      try {
        const course = await deleteInstructorCourse(db, auth.uid, courseId);
        if (!course) return res.status(404).json({ error: 'Course not found.' });
        return res.status(200).json({ success: true, course });
      } catch (error) {
        console.error('Deleting instructor course failed:', error);
        return res.status(500).json({ error: 'Could not delete the course and its assignments.' });
      }
    }

    if (req.method === 'PUT' && ['archive', 'unarchive'].includes(body?.action)) {
      const courseId = String(body?.course_id || '').trim();
      if (!/^[A-Za-z0-9_-]{1,128}$/.test(courseId)) {
        return res.status(400).json({ error: 'A valid course ID is required to archive a course.' });
      }
      try {
        const archived = body.action === 'archive';
        const course = await setInstructorCourseArchived(db, auth.uid, courseId, archived);
        if (!course) return res.status(404).json({ error: 'Course not found.' });
        return res.status(200).json({ success: true, course });
      } catch (error) {
        console.error('Updating instructor course archive status failed:', error);
        return res.status(500).json({ error: 'Could not update course archive status.' });
      }
    }

    if (req.method === 'PUT' && body?.action === 'sync_all_sources') {
      const courseId = String(body?.course_id || '').trim();
      if (!/^[A-Za-z0-9_-]{1,128}$/.test(courseId)) {
        return res.status(400).json({ error: 'A valid course ID is required to sync its assignment sources.' });
      }
      try {
        const courseDoc = await findOwnedCourse(db, auth.uid, courseId);
        if (!courseDoc) return res.status(404).json({ error: 'Course not found.' });
        const course = courseDoc.data();
        const gradescopeCourseId = course.gradescope_course_id;
        const courseWebsiteUrl = parseCourseWebsiteUrl(course.course_website_url || '');
        if (!gradescopeCourseId || !courseWebsiteUrl) {
          return res.status(400).json({ error: 'Configure both Gradescope and a course website before syncing both sources.' });
        }

        const [gradescopeImport, websiteImport] = await Promise.all([
          importCourse(gradescopeCourseId),
          importCourseWebsite(courseWebsiteUrl, course.term || ''),
        ]);
        if (!gradescopeImport ||
            gradescopeImport.course_id !== gradescopeCourseId ||
            !Array.isArray(gradescopeImport.assignments)) {
          throw new Error('Gradescope returned an invalid course response');
        }
        if (!validWebsiteImport(websiteImport) || websiteImport.course_url !== courseWebsiteUrl) {
          throw new Error('Course website importer returned an invalid response.');
        }

        // Combine website items into matching Gradescope items.
        const combinedAssignments = combineSourceAssignments(
          gradescopeImport.assignments,
          websiteImport.assignments,
        );
        const syncedAt = new Date().toISOString();
        const metadata = {
          owner_uid: auth.uid,
          course_id: courseId,
          course_name: course.course_name,
          term: course.term || '',
          gradescope_course_id: gradescopeCourseId,
          gradescope_url: course.gradescope_url || gradescopeImport.course_url || '',
          course_website_url: courseWebsiteUrl,
          course_url: course.gradescope_url || gradescopeImport.course_url || courseWebsiteUrl,
          course_website_synced_at: syncedAt,
          course_website_pages_crawled: websiteImport.pages_crawled,
          course_website_pages_skipped: websiteImport.pages_skipped || 0,
          course_website_candidates_reviewed: websiteImport.candidates_reviewed,
          course_website_term: websiteImport.website_term || null,
        };
        savingProgress();
        const updatedCourse = await syncInstructorCourse(
          db,
          auth.uid,
          courseDoc,
          metadata,
          {
            course_id: gradescopeCourseId,
            course_url: gradescopeImport.course_url || metadata.course_url,
            assignments: combinedAssignments,
          },
          { refreshSources: ['gradescope', 'website'] },
        );
        return res.status(200).json({
          success: true,
          course: {
            ...updatedCourse,
            new_assignment_count: updatedCourse.newly_found_count,
          },
        });
      } catch (error) {
        console.error('Syncing all instructor course sources failed:', error);
        return sourceSyncErrorResponse(res, error, {
          timeoutMessage: 'Course source sync timed out before both sources completed. No assignments were imported.',
          fallbackMessage: 'Could not sync both course sources. No assignments were imported.',
        });
      }
    }

    if (req.method === 'PUT' && body?.action === 'sync_gradescope') {
      const courseId = String(body?.course_id || '').trim();
      if (!/^[A-Za-z0-9_-]{1,128}$/.test(courseId)) {
        return res.status(400).json({ error: 'A valid course ID is required to sync Gradescope.' });
      }
      try {
        const courseDoc = await findOwnedCourse(db, auth.uid, courseId);
        if (!courseDoc) return res.status(404).json({ error: 'Course not found.' });
        const course = courseDoc.data();
        const gradescopeCourseId = course.gradescope_course_id;
        if (!gradescopeCourseId) {
          return res.status(400).json({ error: 'Add a Gradescope Course ID before syncing.' });
        }

        const imported = await importCourse(gradescopeCourseId);
        if (!imported ||
            imported.course_id !== gradescopeCourseId ||
            !Array.isArray(imported.assignments)) {
          throw new Error('Gradescope returned an invalid course response');
        }

        const metadata = {
          owner_uid: auth.uid,
          course_id: courseId,
          course_name: course.course_name,
          term: course.term || '',
          gradescope_course_id: gradescopeCourseId,
          gradescope_url: course.gradescope_url || imported.course_url || '',
          course_website_url: course.course_website_url || '',
          course_url: course.gradescope_url || imported.course_url || '',
        };
        savingProgress();
        const updatedCourse = await syncInstructorCourse(
          db, auth.uid, courseDoc, metadata, imported, { refreshSources: ['gradescope'] },
        );
        return res.status(200).json({
          success: true,
          course: { ...updatedCourse, new_assignment_count: updatedCourse.newly_found_count },
        });
      } catch (error) {
        console.error('Manually syncing instructor course from Gradescope failed:', error);
        return sourceSyncErrorResponse(res, error, {
          timeoutMessage: 'Gradescope took too long to respond. Please try again.',
          fallbackMessage: 'Gradescope couldn’t be synced. Check that the Gradescope course ID is correct, then try again.',
        });
      }
    }

    if (req.method === 'PUT' && body?.action === 'sync_course_website') {
      const courseId = String(body?.course_id || '').trim();
      if (!/^[A-Za-z0-9_-]{1,128}$/.test(courseId)) {
        return res.status(400).json({ error: 'A valid course ID is required to sync its website.' });
      }
      try {
        const courseDoc = await findOwnedCourse(db, auth.uid, courseId);
        if (!courseDoc) return res.status(404).json({ error: 'Course not found.' });
        const course = courseDoc.data();
        const courseWebsiteUrl = parseCourseWebsiteUrl(course.course_website_url || '');
        if (!courseWebsiteUrl) {
          return res.status(400).json({ error: 'Add a valid course website URL before syncing.' });
        }

        const imported = await importCourseWebsite(courseWebsiteUrl, course.term || '');
        if (!validWebsiteImport(imported) || imported.course_url !== courseWebsiteUrl) {
          throw new Error('Course website importer returned an invalid response.');
        }
        const syncedAt = new Date().toISOString();
        const metadata = {
          owner_uid: auth.uid,
          course_id: courseId,
          course_name: course.course_name,
          term: course.term || '',
          gradescope_course_id: course.gradescope_course_id || null,
          gradescope_url: course.gradescope_url || '',
          course_website_url: courseWebsiteUrl,
          course_url: course.course_url || course.gradescope_url || courseWebsiteUrl,
          course_website_synced_at: syncedAt,
          course_website_pages_crawled: imported.pages_crawled,
          course_website_pages_skipped: imported.pages_skipped || 0,
          course_website_candidates_reviewed: imported.candidates_reviewed,
          course_website_term: imported.website_term || null,
        };
        savingProgress();
        const updatedCourse = await syncInstructorCourse(
          db,
          auth.uid,
          courseDoc,
          metadata,
          { ...imported, course_id: course.gradescope_course_id || null },
          { refreshSources: ['website'] },
        );
        return res.status(200).json({
          success: true,
          course: {
            ...updatedCourse,
            new_assignment_count: updatedCourse.newly_found_count,
          },
        });
      } catch (error) {
        console.error('Syncing instructor course website failed:', error);
        return sourceSyncErrorResponse(res, error, {
          timeoutMessage: 'This course page took too long to sync. No assignments were imported. Try a more specific page, such as the course schedule or assignments page.',
          fallbackMessage: 'The course website couldn’t be synced. Check that the link is correct and the site is public, then try again. No assignments were imported.',
        });
      }
    }

    if (req.method === 'PUT' && body?.action === 'add_assignment') {
      const courseId = String(body?.course_id || '').trim();
      const assignmentName = String(body?.assignment_name || '').trim();
      const due = String(body?.due || '').trim();
      const resources = body?.resources === undefined ? [] : parseAssignmentResources(body.resources);
      if (!/^[A-Za-z0-9_-]{1,128}$/.test(courseId) ||
          !assignmentName || assignmentName.length > 200 ||
          !/^\d{4}-\d{2}-\d{2}$/.test(due) ||
          resources === null) {
        return res.status(400).json({ error: 'A valid course, assignment name, and due date are required.' });
      }
      try {
        const assignment = await addInstructorCourseAssignment(db, auth.uid, courseId, assignmentName, due, resources);
        if (!assignment) return res.status(404).json({ error: 'Course not found.' });
        return res.status(200).json({ success: true, assignment });
      } catch (error) {
        console.error('Adding instructor course assignment failed:', error);
        return res.status(500).json({ error: 'Could not add the assignment.' });
      }
    }

    if (req.method === 'PUT' && body?.action === 'remove_assignment') {
      const courseId = String(body?.course_id || '').trim();
      const assignmentId = String(body?.assignment_id || '').trim();
      if (!/^[A-Za-z0-9_-]{1,128}$/.test(courseId) ||
          !/^[A-Za-z0-9_-]{1,128}(#v\d{1,4})?$/.test(assignmentId)) {
        return res.status(400).json({ error: 'A valid course and assignment ID are required.' });
      }
      try {
        const result = await removeInstructorCourseAssignment(db, auth.uid, courseId, assignmentId);
        if (!result) return res.status(404).json({ error: 'Course not found.' });
        if (!result.removed) return res.status(404).json({ error: 'Assignment not found.' });
        return res.status(200).json({ success: true, course_id: courseId });
      } catch (error) {
        console.error('Removing instructor course assignment failed:', error);
        return res.status(500).json({ error: 'Could not remove the assignment.' });
      }
    }

    if (req.method === 'PUT' &&
        (body?.action === 'update_assignment' ||
         body?.action === 'update_synced_assignment' ||
         (body?.assignment_id && body?.assignment_name && body?.course_id))) {
      const courseId = String(body?.course_id || '').trim();
      const assignmentId = String(body?.assignment_id || '').trim();
      const assignmentName = String(body?.assignment_name || '').trim();
      const due = String(body?.due || '').trim();
      const resources = body?.resources === undefined ? undefined : parseAssignmentResources(body.resources);
      if (!/^[A-Za-z0-9_-]{1,128}$/.test(courseId) ||
          !/^[A-Za-z0-9_-]{1,128}(#v\d{1,4})?$/.test(assignmentId) ||
          !assignmentName || assignmentName.length > 200 ||
          !/^\d{4}-\d{2}-\d{2}$/.test(due) ||
          resources === null) {
        return res.status(400).json({ error: 'A valid course, assignment name, and due date are required.' });
      }
      try {
        const updates = {
          assignment_name: assignmentName,
          due: due || null,
        };
        if (resources !== undefined) updates.resources = resources;
        const collectionOverride = body?.action === 'update_synced_assignment'
          ? 'instructor_course_assignment_reviews'
          : null;
        const result = await updateInstructorCourseAssignment(
          db,
          auth.uid,
          courseId,
          assignmentId,
          updates,
          collectionOverride,
        );
        if (!result) return res.status(404).json({ error: 'Course not found.' });
        if (result.notFound) return res.status(404).json({ error: 'Assignment not found.' });
        return res.status(200).json({ success: true, assignment: result });
      } catch (error) {
        console.error('Updating instructor course assignment failed:', error);
        return res.status(500).json({ error: 'Could not update the assignment.' });
      }
    }

    if (req.method === 'PUT' && body?.action === 'review_synced_assignments') {
      const courseId = String(body?.course_id || '').trim();
      const approvedIds = body?.approved_assignment_ids;
      if (!/^[A-Za-z0-9_-]{1,128}$/.test(courseId) ||
          !Array.isArray(approvedIds) ||
          approvedIds.some(id => typeof id !== 'string')) {
        return res.status(400).json({ error: 'A valid course and approved assignment list are required.' });
      }
      try {
        const result = await reviewSyncedAssignments(db, auth.uid, courseId, approvedIds);
        if (!result) return res.status(404).json({ error: 'Course not found.' });
        if (result.invalid) return res.status(400).json({ error: 'The review list contains an unknown assignment.' });
        if (result.undated) {
          return res.status(400).json({ error: `Add a due date to “${result.undated}” before adding it, or leave it unchecked.` });
        }
        return res.status(200).json({ success: true, course: result });
      } catch (error) {
        console.error('Reviewing newly synced assignments failed:', error);
        return res.status(500).json({ error: 'Could not save assignment review.' });
      }
    }

    if (req.method === 'PUT' && body?.action === 'finalize') {
      const courseId = String(body?.course_id || '').trim();
      const approvedAssignmentIds = body?.approved_assignment_ids;
      if (!/^[A-Za-z0-9_-]{1,128}$/.test(courseId) || !Array.isArray(approvedAssignmentIds) ||
          approvedAssignmentIds.some(id => typeof id !== 'string')) {
        return res.status(400).json({ error: 'A valid course ID and approved assignment list are required.' });
      }
      try {
        const course = await finalizeReviewedCourse(db, auth.uid, courseId, approvedAssignmentIds);
        if (!course) return res.status(404).json({ error: 'Course review not found.' });
        if (course.undated) {
          return res.status(400).json({ error: `Add a due date to “${course.undated}” before adding it, or leave it unchecked.` });
        }
        return res.status(200).json({ success: true, course });
      } catch (error) {
        console.error('Finalizing instructor course review failed:', error);
        return res.status(500).json({ error: 'Could not finalize course assignments.' });
      }
    }

    const courseName = String(body?.course_name || '').trim();
    const term = String(body?.term || '').trim();
    if (!courseName || courseName.length > 120 || term.length > 80) {
      return res.status(400).json({ error: 'Enter a course name (up to 120 characters); term must be within 80 characters.' });
    }

    if (req.method === 'PUT') {
      const courseId = String(body?.course_id || '').trim();
      if (!/^[A-Za-z0-9_-]{1,128}$/.test(courseId)) {
        return res.status(400).json({ error: 'A valid course ID is required to edit a course.' });
      }

      const snapshot = await db.collection('instructor_courses')
        .where('owner_uid', '==', auth.uid)
        .where('course_id', '==', courseId)
        .get();
      const existingCourse = snapshot.docs[0];
      if (!existingCourse) {
        return res.status(404).json({ error: 'Course not found.' });
      }

      const existingCourseData = existingCourse.data();
      const gradescopeInput = String(
        body?.gradescope_url ?? body?.gradescope_course_id ??
        existingCourseData.gradescope_course_id ?? '',
      ).trim();
      const gradescopeCourseId = gradescopeInput ? parseCourseId(gradescopeInput) : null;
      if (gradescopeInput && !gradescopeCourseId) {
        return res.status(400).json({ error: 'Enter a numeric Gradescope Course ID.' });
      }
      const courseWebsiteUrl = parseCourseWebsiteUrl(
        body?.course_website_url ?? existingCourseData.course_website_url ?? '',
      );
      if (courseWebsiteUrl === null) {
        return res.status(400).json({ error: 'Enter a valid course website URL beginning with http:// or https://.' });
      }
      const existingCourseWebsiteUrl = parseCourseWebsiteUrl(existingCourseData.course_website_url || '') || '';
      // Auto-sync only the sources whose identifier changed.
      const gradescopeChanged = Boolean(gradescopeCourseId) &&
        gradescopeCourseId !== (existingCourseData.gradescope_course_id || null);
      const websiteChanged = Boolean(courseWebsiteUrl) && courseWebsiteUrl !== existingCourseWebsiteUrl;
      const gradescopeIdUnchanged = gradescopeCourseId === (existingCourseData.gradescope_course_id || null);
      if (gradescopeChanged) {
        const gradescopeOwner = await courseUsingGradescopeId(db, gradescopeCourseId, existingCourse.id);
        if (gradescopeOwner) return gradescopeInUseResponse(res);
      }

      let gradescopeImport = null;
      let websiteImport = null;
      if (gradescopeChanged || websiteChanged) {
        try {
          [gradescopeImport, websiteImport] = await Promise.all([
            gradescopeChanged ? importCourse(gradescopeCourseId) : null,
            websiteChanged ? importCourseWebsite(courseWebsiteUrl, term) : null,
          ]);
          if (gradescopeChanged && (
            !gradescopeImport ||
            gradescopeImport.course_id !== gradescopeCourseId ||
            !Array.isArray(gradescopeImport.assignments))) {
            throw new Error('Gradescope returned an invalid course response');
          }
          if (websiteChanged &&
              (!validWebsiteImport(websiteImport) || websiteImport.course_url !== courseWebsiteUrl)) {
            throw new Error('Course website importer returned an invalid response.');
          }
        } catch (error) {
          // Don't save: a changed source that failed to sync would never retry.
          console.error('Syncing changed course sources failed:', error);
          return sourceSyncErrorResponse(res, error, {
            timeoutMessage: 'Syncing the changed course source timed out. Your changes were not saved.',
            fallbackMessage: 'Could not sync the changed course source. Your changes were not saved.',
          });
        }
      }
      let imported = null;
      if (gradescopeImport || websiteImport) {
        imported = {
          course_id: gradescopeCourseId,
          course_url: gradescopeImport?.course_url || '',
          assignments: combineSourceAssignments(
            gradescopeImport?.assignments || [],
            websiteImport?.assignments || [],
          ),
        };
      }

      const metadata = {
        owner_uid: auth.uid,
        course_id: courseId,
        course_name: courseName,
        term,
        gradescope_course_id: gradescopeCourseId,
        gradescope_url: imported?.course_url ||
          (gradescopeCourseId ? `https://www.gradescope.com/courses/${gradescopeCourseId}` : '') ||
          (gradescopeIdUnchanged ? existingCourseData.gradescope_url || '' : ''),
        course_website_url: courseWebsiteUrl,
        course_url: imported?.course_url ||
          (gradescopeCourseId ? `https://www.gradescope.com/courses/${gradescopeCourseId}` : ''),
        ...(websiteImport ? {
          course_website_synced_at: new Date().toISOString(),
          course_website_pages_crawled: websiteImport.pages_crawled,
          course_website_pages_skipped: websiteImport.pages_skipped || 0,
          course_website_candidates_reviewed: websiteImport.candidates_reviewed,
          course_website_term: websiteImport.website_term || null,
        } : {}),
      };
      if (imported) savingProgress();
      const updatedCourse = imported
        ? await syncInstructorCourse(db, auth.uid, existingCourse, metadata, imported)
        : { ...existingCourse.data(), ...metadata };
      if (!imported) {
        await db.collection('instructor_courses').doc(existingCourse.id).set(metadata, { merge: true });
      }
      const { description: _description, ...updatedCourseData } = updatedCourse;
      // Tell the instructor what the automatic sync did, even when nothing was new.
      const syncSummary = {
        ...(gradescopeImport ? { gradescope: { found: gradescopeImport.assignments.length } } : {}),
        ...(websiteImport ? { website: { found: websiteImport.assignments.length } } : {}),
      };
      return res.status(200).json({
        success: true,
        course: {
          ...updatedCourseData,
          new_assignment_count: (updatedCourseData.new_assignments || []).length,
        },
        sync_summary: syncSummary,
      });
    }

    const gradescopeInput = String(body?.gradescope_url || body?.course_id || body?.course_code || '').trim();
    const gradescopeCourseId = gradescopeInput ? parseCourseId(gradescopeInput) : null;
    if (gradescopeInput && !gradescopeCourseId) {
      return res.status(400).json({ error: 'Enter a numeric Gradescope Course ID.' });
    }

    const courseWebsiteUrl = parseCourseWebsiteUrl(body?.course_website_url);
    if (courseWebsiteUrl === null) {
      return res.status(400).json({ error: 'Enter a valid course website URL beginning with http:// or https://.' });
    }
    const gradescopeOwner = await courseUsingGradescopeId(db, gradescopeCourseId);
    if (gradescopeOwner) return gradescopeInUseResponse(res);
    let imported;
    let websiteImport = null;
    try {
      // Both sources are imported when provided; the course is created only if both succeed.
      const tagSource = source => error => {
        if (error && typeof error === 'object') error.importSource = source;
        throw error;
      };
      const [gradescopeImport, websiteResult] = await Promise.all([
        gradescopeInput ? importCourse(gradescopeCourseId).catch(tagSource('gradescope')) : null,
        courseWebsiteUrl ? importCourseWebsite(courseWebsiteUrl, term).catch(tagSource('website')) : null,
      ]);
      if (gradescopeInput && (
        !gradescopeImport ||
        !/^\d{1,20}$/.test(gradescopeImport.course_id) ||
        (gradescopeCourseId && gradescopeImport.course_id !== gradescopeCourseId) ||
        !Array.isArray(gradescopeImport.assignments))) {
        const error = new Error('Gradescope returned an invalid course response');
        error.importSource = 'gradescope';
        throw error;
      }
      if (courseWebsiteUrl &&
          (!validWebsiteImport(websiteResult) || websiteResult.course_url !== courseWebsiteUrl)) {
        const error = new Error('Course website importer returned an invalid response.');
        error.importSource = 'website';
        throw error;
      }
      imported = gradescopeImport || { course_id: null, course_url: '', assignments: [] };
      websiteImport = websiteResult;
    } catch (error) {
      if (error?.importSource === 'website') {
        console.error('Course website import failed while creating a course:', error);
        return sourceSyncErrorResponse(res, error, {
          timeoutMessage: 'The course website sync timed out. The course was not created.',
          fallbackMessage: 'Could not sync the course website. The course was not created.',
        });
      }
      {
        console.error('Gradescope course import failed:', error);
        return sourceSyncErrorResponse(res, error, {
          timeoutMessage: 'Gradescope took too long to respond. The course was not created. Please try again.',
          fallbackMessage: 'Gradescope couldn’t be synced. Check that the Gradescope course ID is correct. The course was not created.',
        });
      }
    }
    if (websiteImport) {
      imported = {
        ...imported,
        assignments: combineSourceAssignments(imported.assignments, websiteImport.assignments),
      };
    }

    try {
      const metadata = {
        course_key: `course-${randomUUID()}`,
        course_name: courseName,
        term,
        gradescope_url: imported.course_url ||
          (imported.course_id ? `https://www.gradescope.com/courses/${imported.course_id}` : ''),
        course_website_url: courseWebsiteUrl,
        ...(websiteImport ? {
          course_website_synced_at: new Date().toISOString(),
          course_website_pages_crawled: websiteImport.pages_crawled,
          course_website_pages_skipped: websiteImport.pages_skipped || 0,
          course_website_candidates_reviewed: websiteImport.candidates_reviewed,
          course_website_term: websiteImport.website_term || null,
        } : {}),
      };
      savingProgress();
      const course = await stageImportedCourse(db, auth.uid, imported, metadata);
      return res.status(200).json({ success: true, course });
    } catch (error) {
      console.error('Saving instructor course failed:', error);
      return res.status(500).json({ error: 'Could not save the imported course' });
    }
  } catch (error) {
    console.error('Instructor courses request failed:', error);
    return res.status(500).json({ error: 'Could not load instructor courses' });
  }
}
