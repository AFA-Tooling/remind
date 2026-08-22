import test from 'node:test';
import assert from 'node:assert/strict';

import { runStudyAction } from './study.js';
import { DEFAULT_COURSE_CODE, DEFAULT_DAYS_BEFORE_DEADLINE } from '../students/defaults.js';

// Consent used to write only a study_participants doc. The daily pipeline iterates
// `students`, so a consented participant who never signed in to the dashboard
// received nothing at all. Consent now enrolls them directly.

/** Minimal in-memory Firestore covering the surface runStudyAction touches. */
function makeDb(seed = {}) {
  const data = new Map();
  for (const [collection, docs] of Object.entries(seed)) {
    for (const [id, value] of Object.entries(docs)) data.set(`${collection}/${id}`, value);
  }

  const snapshot = (key) => ({
    id: key.slice(key.indexOf('/') + 1),
    exists: data.has(key),
    data: () => data.get(key),
  });

  const docRef = (collection, id) => {
    const key = `${collection}/${id}`;
    return {
      async get() { return snapshot(key); },
      async set(value, options) {
        data.set(key, options?.merge ? { ...(data.get(key) || {}), ...value } : value);
      },
      async delete() { data.delete(key); },
    };
  };

  return {
    read: (collection, id) => data.get(`${collection}/${id}`),
    has: (collection, id) => data.has(`${collection}/${id}`),
    collection(collection) {
      return {
        doc: (id) => docRef(collection, id),
        async get() {
          const docs = [...data.keys()]
            .filter((k) => k.startsWith(`${collection}/`))
            .map(snapshot);
          return { docs, empty: docs.length === 0 };
        },
      };
    },
    batch() {
      const writes = [];
      return {
        set(ref, value, options) { writes.push(() => ref.set(value, options)); },
        update(ref, value) { writes.push(() => ref.set(value, { merge: true })); },
        delete(ref) { writes.push(() => ref.delete()); },
        async commit() { for (const write of writes) await write(); },
      };
    },
  };
}

function makeRes() {
  return {
    statusCode: null,
    body: null,
    status(code) { this.statusCode = code; return this; },
    json(payload) { this.body = payload; return this; },
  };
}

async function consent(db, emails, source = 'csv', courseCode = 'CS61A') {
  const res = makeRes();
  await runStudyAction(
    { method: 'POST', query: { action: 'consent' }, body: { emails, source, course_code: courseCode } },
    res,
    db,
  );
  return res;
}

test('consenting enrolls the student for email without any sign-in', async () => {
  const db = makeDb();
  const res = await consent(db, ['jo@berkeley.edu']);

  assert.equal(res.statusCode, 200);
  assert.equal(res.body.added, 1);
  assert.equal(res.body.enrolled, 1);

  const student = db.read('students', 'jo@berkeley.edu');
  assert.equal(student.email_pref, true);
  assert.equal(student.days_before_deadline, DEFAULT_DAYS_BEFORE_DEADLINE);
  assert.equal(student.enrolled_via, 'consent');
  assert.deepEqual(student.category_prefs, {
    lab: true, homework: true, midterm: true, quiz: true, project: true,
  });
});

test('enrollment takes course_code from the roster so the pipeline can route it', async () => {
  const db = makeDb({
    class_roster: { 'jo@berkeley.edu': { name: 'Jo Student', course_code: 'CS61A' } },
  });
  await consent(db, ['jo@berkeley.edu']);

  const student = db.read('students', 'jo@berkeley.edu');
  assert.equal(student.course_code, 'CS61A');
  assert.equal(student.preferred_first_name, 'Jo');
});

// Staff and late adds consent without being on the roster; they still need a
// course_code or they match no assignment catalog and are silently dropped.
// They fall back to whichever course they were consented under (the admin's
// active course tab), not a hardcoded global default.
test('enrollment falls back to the course consented under for someone not on the roster', async () => {
  const db = makeDb();
  await consent(db, ['staff@berkeley.edu'], 'csv', 'CS61A');

  assert.equal(db.read('students', 'staff@berkeley.edu').course_code, DEFAULT_COURSE_CODE);
});

test('consenting under a non-default course still falls back correctly without a roster entry', async () => {
  const db = makeDb();
  await consent(db, ['staff@berkeley.edu'], 'csv', 'CS10');

  assert.equal(db.read('students', 'staff@berkeley.edu').course_code, 'CS10');
});

// A student's own choices must always beat the enrollment defaults.
test('an existing student doc is left completely untouched', async () => {
  const existing = {
    email: 'jo@berkeley.edu',
    email_pref: false,
    days_before_deadline: 1,
    course_code: 'CS61A',
    created_at: '2026-01-01T00:00:00.000Z',
    updated_at: '2026-02-02T00:00:00.000Z',
  };
  const db = makeDb({ students: { 'jo@berkeley.edu': { ...existing } } });

  const res = await consent(db, ['jo@berkeley.edu']);

  assert.equal(res.body.enrolled, 0);
  assert.deepEqual(db.read('students', 'jo@berkeley.edu'), existing);
});

// Re-uploading the roster CSV is the operator's repair tool, so enrollment runs
// over every submitted email rather than only the newly-added participants.
test('re-consenting an existing participant repairs a missing student doc', async () => {
  const db = makeDb({
    study_participants: {
      'jo@berkeley.edu': { email: 'jo@berkeley.edu', course_code: 'CS61A', group: 1, source: 'csv' },
    },
  });

  const res = await consent(db, ['jo@berkeley.edu']);

  assert.equal(res.body.added, 0);
  assert.equal(res.body.alreadyPresent, 1);
  assert.equal(res.body.enrolled, 1);
  assert.equal(db.read('students', 'jo@berkeley.edu').email_pref, true);
});

// Group 2 is enrolled too. apply_study_gate in the pipeline is the sole authority
// on who is actually sent to, so the doc is inert until access opens — and opening
// access then needs no second migration.
test('group 2 participants are enrolled alongside group 1', async () => {
  const db = makeDb({ study_config: { CS61A: { randomized: true, access_open: false } } });

  const res = await consent(db, ['a@berkeley.edu', 'b@berkeley.edu']);

  assert.equal(res.body.assigned, 2);
  const groups = ['a@berkeley.edu', 'b@berkeley.edu']
    .map((e) => db.read('study_participants', e).group)
    .sort();
  assert.deepEqual(groups, [1, 2], 'balanced randomization should split the pair');
  assert.equal(res.body.enrolled, 2);
  for (const email of ['a@berkeley.edu', 'b@berkeley.edu']) {
    assert.equal(db.read('students', email).email_pref, true);
  }
});

test('an all-invalid consent upload enrolls nobody', async () => {
  const db = makeDb();
  const res = await consent(db, ['not-an-email']);

  assert.equal(res.body.skipped, 1);
  assert.equal(res.body.enrolled, 0);
  assert.equal(db.has('students', 'not-an-email'), false);
});

// ---- Per-course scoping ----
// Group 1/2 randomization, access, and export are independent per course: acting
// on one course's data must never read or write another course's participants or
// study_config doc.

test('consent stamps the course it was submitted under onto the participant doc', async () => {
  const db = makeDb();
  await consent(db, ['jo@berkeley.edu'], 'csv', 'CS10');

  assert.equal(db.read('study_participants', 'jo@berkeley.edu').course_code, 'CS10');
});

test('overview requires a course_code', async () => {
  const db = makeDb();
  const res = makeRes();
  await runStudyAction({ method: 'GET', query: { action: 'overview' } }, res, db);

  assert.equal(res.statusCode, 400);
});

test('overview only returns participants for the requested course', async () => {
  const db = makeDb({
    study_participants: {
      'a@berkeley.edu': { email: 'a@berkeley.edu', course_code: 'CS61A', group: 1 },
      'b@berkeley.edu': { email: 'b@berkeley.edu', course_code: 'CS10', group: 1 },
    },
  });
  const res = makeRes();
  await runStudyAction({ method: 'GET', query: { action: 'overview', course_code: 'CS61A' } }, res, db);

  assert.equal(res.body.participants.length, 1);
  assert.equal(res.body.participants[0].email, 'a@berkeley.edu');
  assert.equal(res.body.counts.total, 1);
});

test('randomizing one course never assigns or touches another course\'s participants', async () => {
  const db = makeDb({
    study_participants: {
      'cs61a@berkeley.edu': { email: 'cs61a@berkeley.edu', course_code: 'CS61A', group: null },
      'cs10@berkeley.edu': { email: 'cs10@berkeley.edu', course_code: 'CS10', group: null },
    },
  });
  const res = makeRes();
  await runStudyAction(
    { method: 'POST', query: { action: 'randomize' }, body: { course_code: 'CS61A' } },
    res,
    db,
  );

  assert.equal(res.statusCode, 200);
  assert.equal(res.body.assigned, 1);
  assert.notEqual(db.read('study_participants', 'cs61a@berkeley.edu').group, null);
  assert.equal(db.read('study_participants', 'cs10@berkeley.edu').group, null, 'CS10 participant must be untouched');
  assert.equal(db.has('study_config', 'CS10'), false, 'CS10 config must not be created by a CS61A randomize');
  assert.equal(db.read('study_config', 'CS61A').randomized, true);
});

test('opening access for one course does not open it for another', async () => {
  const db = makeDb();
  const res = makeRes();
  await runStudyAction(
    { method: 'POST', query: { action: 'open-access' }, body: { confirm: true, course_code: 'CS61A' } },
    res,
    db,
  );

  assert.equal(db.read('study_config', 'CS61A').access_open, true);
  assert.equal(db.has('study_config', 'CS10'), false);
});

test('export only includes the requested course and group', async () => {
  const db = makeDb({
    study_participants: {
      'a@berkeley.edu': { email: 'a@berkeley.edu', course_code: 'CS61A', group: 1 },
      'b@berkeley.edu': { email: 'b@berkeley.edu', course_code: 'CS10', group: 1 },
      'c@berkeley.edu': { email: 'c@berkeley.edu', course_code: 'CS61A', group: 2 },
    },
  });
  const res = makeRes();
  await runStudyAction(
    { method: 'GET', query: { action: 'export', group: '1', course_code: 'CS61A' } },
    res,
    db,
  );

  assert.deepEqual(res.body.emails, ['a@berkeley.edu']);
});
