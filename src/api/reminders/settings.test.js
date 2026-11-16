import test from 'node:test';
import assert from 'node:assert/strict';

import handler from './settings.js';

// Coverage for the "Advanced options" extra reminder days on the save endpoint,
// plus regression checks that ordinary saves (no extras) behave exactly as before.

const CALLER = 'student@berkeley.edu';

function isPlainObject(v) {
  return v !== null && typeof v === 'object' && !Array.isArray(v);
}

// Firestore set({merge:true}) merges nested maps key-by-key and replaces arrays.
// The fake must do the same, or a "cleared row" bug would be invisible here.
function deepMerge(base, patch) {
  const out = { ...(base || {}) };
  for (const [k, v] of Object.entries(patch)) {
    out[k] = isPlainObject(v) && isPlainObject(out[k]) ? deepMerge(out[k], v) : v;
  }
  return out;
}

function makeDb(seed = {}) {
  const data = new Map();
  for (const [collection, docs] of Object.entries(seed)) {
    for (const [id, value] of Object.entries(docs)) data.set(`${collection}/${id}`, structuredClone(value));
  }
  const writes = [];
  return {
    _data: data,
    _writes: writes,
    collection(collection) {
      return {
        doc(id) {
          const key = `${collection}/${id}`;
          return {
            async get() {
              return { exists: data.has(key), data: () => structuredClone(data.get(key)) };
            },
            async set(value, options) {
              writes.push(key);
              data.set(key, options?.merge ? deepMerge(data.get(key), value) : value);
            },
            async update(value) {
              writes.push(key);
              data.set(key, { ...(data.get(key) || {}), ...value });
            },
          };
        },
      };
    },
  };
}

function makeRes() {
  return {
    statusCode: null,
    body: null,
    status(code) { this.statusCode = code; return this; },
    json(body) { this.body = body; return this; },
  };
}

/** Fakes for every outside dependency; courseCode is what the roster says. */
function makeDeps(db, { courseCode = 'CS61A', studyStatus = 'autoremind', authorized = true } = {}) {
  const welcomeEmails = [];
  return {
    welcomeEmails,
    verifyUserAuth: async () => (authorized
      ? { authorized: true, email: CALLER }
      : { authorized: false, error: 'Unauthorized' }),
    getDb: () => db,
    getStudyStatus: async () => ({ status: studyStatus }),
    syncStudentCourseFromRoster: async (_db, _email, existing) => ({
      data: existing || {},
      courseCode,
      onRoster: !!courseCode,
      patched: false,
    }),
    sendWelcomeEmail: async (args) => { welcomeEmails.push(args); return { success: true }; },
  };
}

/** A request body like the dashboard sends. */
function body(extra = {}) {
  return {
    channels: { email: true },
    days_before: 3,
    preferred_first_name: 'Sam',
    category_prefs: { lab: true, homework: true, midterm: true, quiz: true, project: true },
    ...extra,
  };
}

async function save(db, reqBody, depOpts) {
  const res = makeRes();
  await handler({ method: 'POST', body: reqBody }, res, makeDeps(db, depOpts));
  return res;
}

const stored = (db) => db._data.get(`students/${CALLER}`);

// --- saving extras ----------------------------------------------------------

test('saves extra reminder days, cleaned, with every course row present', async () => {
  const db = makeDb({ students: { [CALLER]: { welcome_email_sent: true } } });
  const res = await save(db, body({
    extra_reminder_days: { project: [1, 1, 9, -2, 2.5], other: [0], made_up_type: [2] },
  }));
  assert.equal(res.statusCode, 200);
  assert.deepEqual(stored(db).extra_reminder_days, {
    other: [0], lab: [], homework: [], midterm: [], quiz: [], project: [1],
  });
});

test('omitting extra_reminder_days leaves the stored extras untouched', async () => {
  const db = makeDb({ students: { [CALLER]: {
    welcome_email_sent: true,
    extra_reminder_days: { project: [1], other: [] },
  } } });
  const res = await save(db, body()); // older dashboards / failed grid load send no extras
  assert.equal(res.statusCode, 200);
  assert.deepEqual(stored(db).extra_reminder_days, { project: [1], other: [] });
});

test('unticking every extra really clears it (nested merge does not keep old days)', async () => {
  const db = makeDb({ students: { [CALLER]: {
    welcome_email_sent: true,
    extra_reminder_days: { project: [1, 0], lab: [2], other: [4] },
  } } });
  await save(db, body({ extra_reminder_days: {} }));
  const extras = stored(db).extra_reminder_days;
  assert.deepEqual(extras.project, []);
  assert.deepEqual(extras.lab, []);
  assert.deepEqual(extras.other, []);
});

test('changing one row keeps the new value for that row only', async () => {
  const db = makeDb({ students: { [CALLER]: {
    welcome_email_sent: true,
    extra_reminder_days: { project: [1], lab: [0] },
  } } });
  await save(db, body({ extra_reminder_days: { project: [2], lab: [0] } }));
  assert.deepEqual(stored(db).extra_reminder_days.project, [2]);
  assert.deepEqual(stored(db).extra_reminder_days.lab, [0]);
});

test('an extra equal to the slider day is kept (so it survives the slider moving)', async () => {
  const db = makeDb({ students: { [CALLER]: { welcome_email_sent: true } } });
  await save(db, body({ days_before: 1, extra_reminder_days: { project: [1] } }));
  assert.deepEqual(stored(db).extra_reminder_days.project, [1]);
  assert.equal(stored(db).days_before_deadline, 1);
});

test('student with no course only gets the "other" row', async () => {
  const db = makeDb({ students: { [CALLER]: { welcome_email_sent: true } } });
  const res = await save(db, body({
    category_prefs: undefined,
    extra_reminder_days: { project: [1], other: [2] },
  }), { courseCode: null });
  assert.equal(res.statusCode, 200);
  assert.deepEqual(stored(db).extra_reminder_days, { other: [2] });
});

test('rows come from the roster course, not whatever types the request names', async () => {
  const db = makeDb({ students: { [CALLER]: { welcome_email_sent: true } } });
  // CS10 has a "postterm" type that CS61A does not.
  await save(db, body({ extra_reminder_days: { postterm: [1], project: [2] } }), { courseCode: 'CS61A' });
  assert.equal('postterm' in stored(db).extra_reminder_days, false);
  assert.deepEqual(stored(db).extra_reminder_days.project, [2]);
});

// --- rejecting bad input ----------------------------------------------------

for (const bad of [null, [1, 2], 'project', 3]) {
  test(`extra_reminder_days = ${JSON.stringify(bad)} is rejected with 400 and nothing is written`, async () => {
    const db = makeDb({ students: { [CALLER]: {
      welcome_email_sent: true, days_before_deadline: 5, extra_reminder_days: { project: [1] },
    } } });
    const res = await save(db, body({ days_before: 2, extra_reminder_days: bad }));
    assert.equal(res.statusCode, 400);
    assert.equal(db._writes.length, 0, 'a rejected save must not change anything');
    assert.equal(stored(db).days_before_deadline, 5);
    assert.deepEqual(stored(db).extra_reminder_days, { project: [1] });
  });
}

test('not logged in → 401, nothing written', async () => {
  const db = makeDb({});
  const res = await save(db, body({ extra_reminder_days: { project: [1] } }), { authorized: false });
  assert.equal(res.statusCode, 401);
  assert.equal(db._writes.length, 0);
});

test('not consented to the study → 403, extras not saved', async () => {
  const db = makeDb({ students: { [CALLER]: {} } });
  const res = await save(db, body({ extra_reminder_days: { project: [1] } }), { studyStatus: 'not_consented' });
  assert.equal(res.statusCode, 403);
  assert.equal(db._writes.length, 0);
});

test('waitlisted students still save extras (they activate when access opens)', async () => {
  const db = makeDb({ students: { [CALLER]: {} } });
  const res = await save(db, body({ extra_reminder_days: { project: [1] } }), { studyStatus: 'waitlisted' });
  assert.equal(res.statusCode, 200);
  assert.equal(res.body.waitlisted, true);
  assert.deepEqual(stored(db).extra_reminder_days.project, [1]);
});

// --- ordinary saves still work like before ----------------------------------

test('regular save without extras still stores slider, channels and type prefs', async () => {
  const db = makeDb({ students: { [CALLER]: { welcome_email_sent: true } } });
  const res = await save(db, body({
    days_before: 4,
    category_prefs: { lab: true, homework: false, midterm: true, quiz: true, project: true },
  }));
  assert.equal(res.statusCode, 200);
  const s = stored(db);
  assert.equal(s.days_before_deadline, 4);
  assert.equal(s.email_pref, true);
  assert.equal(s.category_prefs.homework, false);
  assert.equal('extra_reminder_days' in s, false, 'no extras field is created when none are sent');
});

test('first save with email on still sends the welcome email once', async () => {
  const db = makeDb({ students: { [CALLER]: {} } });
  const deps = makeDeps(db);
  const res = makeRes();
  await handler({ method: 'POST', body: body({ extra_reminder_days: { project: [1] } }) }, res, deps);
  assert.equal(res.statusCode, 200);
  assert.equal(deps.welcomeEmails.length, 1);
  assert.equal(stored(db).welcome_email_sent, true);
});

test('missing days_before is still rejected', async () => {
  const db = makeDb({ students: { [CALLER]: {} } });
  const res = await save(db, { channels: { email: true }, extra_reminder_days: { project: [1] } });
  assert.equal(res.statusCode, 400);
  assert.equal(db._writes.length, 0);
});
