import test from 'node:test';
import assert from 'node:assert/strict';

import handler from './get.js';
import saveHandler from './settings.js';

// Coverage for returning extra reminder days to the dashboard grid, plus a
// save → load round trip through both real handlers.

const CALLER = 'student@berkeley.edu';
const EMPTY_CS61A = { other: [], lab: [], homework: [], midterm: [], quiz: [], project: [] };

function isPlainObject(v) {
  return v !== null && typeof v === 'object' && !Array.isArray(v);
}

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
  return {
    _data: data,
    collection(collection) {
      return {
        doc(id) {
          const key = `${collection}/${id}`;
          return {
            async get() {
              return { exists: data.has(key), data: () => structuredClone(data.get(key)) };
            },
            async set(value, options) {
              data.set(key, options?.merge ? deepMerge(data.get(key), value) : value);
            },
            async update(value) {
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

function makeDeps(db, { courseCode = 'CS61A' } = {}) {
  return {
    verifyUserAuth: async () => ({ authorized: true, email: CALLER }),
    getDb: () => db,
    getStudyStatus: async () => ({ status: 'autoremind' }),
    syncStudentCourseFromRoster: async (_db, _email, existing) => ({
      data: existing || {},
      courseCode,
      onRoster: !!courseCode,
      patched: false,
    }),
    sendWelcomeEmail: async () => ({ success: true }),
  };
}

async function load(db, depOpts) {
  const res = makeRes();
  await handler({ method: 'GET' }, res, makeDeps(db, depOpts));
  return res;
}

test('returns the stored extra days, with empty rows filled in', async () => {
  const db = makeDb({ students: { [CALLER]: { extra_reminder_days: { project: [1], lab: [0] } } } });
  const res = await load(db);
  assert.equal(res.statusCode, 200);
  assert.deepEqual(res.body.data.extra_reminder_days, { ...EMPTY_CS61A, project: [1], lab: [0] });
});

test('student who never saved extras gets every row as [] (grid still renders)', async () => {
  const db = makeDb({ students: { [CALLER]: { days_before_deadline: 3 } } });
  const res = await load(db);
  assert.equal(res.statusCode, 200);
  assert.deepEqual(res.body.data.extra_reminder_days, EMPTY_CS61A);
});

for (const broken of [[1, 2], 'project', 7, { project: 'oops', lab: [1, 'x', 99] }]) {
  test(`broken stored value ${JSON.stringify(broken)} does not crash the load`, async () => {
    const db = makeDb({ students: { [CALLER]: { extra_reminder_days: broken } } });
    const res = await load(db);
    assert.equal(res.statusCode, 200);
    const extras = res.body.data.extra_reminder_days;
    assert.deepEqual(Object.keys(extras).sort(), Object.keys(EMPTY_CS61A).sort());
    for (const days of Object.values(extras)) {
      assert.ok(days.every((d) => Number.isInteger(d) && d >= 0 && d <= 5));
    }
  });
}

test('student with no course only gets the "other" row', async () => {
  const db = makeDb({ students: { [CALLER]: { extra_reminder_days: { other: [2], project: [1] } } } });
  const res = await load(db, { courseCode: null });
  assert.deepEqual(res.body.data.extra_reminder_days, { other: [2] });
});

test('stored days for types the course no longer has are not returned', async () => {
  const db = makeDb({ students: { [CALLER]: { extra_reminder_days: { postterm: [1], project: [2] } } } });
  const res = await load(db);
  assert.equal('postterm' in res.body.data.extra_reminder_days, false);
  assert.deepEqual(res.body.data.extra_reminder_days.project, [2]);
});

test('existing fields are still returned as before', async () => {
  const db = makeDb({ students: { [CALLER]: {
    days_before_deadline: 2, email_pref: true, category_prefs: { homework: false },
  } } });
  const res = await load(db);
  const d = res.body.data;
  assert.equal(d.days_before_deadline, 2);
  assert.equal(d.email_pref, true);
  assert.equal(d.category_prefs.homework, false);
  assert.equal(d.course_code, 'CS61A');
});

test('unknown student is still a 404', async () => {
  const res = await load(makeDb({}));
  assert.equal(res.statusCode, 404);
});

// --- round trip: what the dashboard saves is what it loads back -------------

test('save then load returns exactly what the grid sent (after cleanup)', async () => {
  const db = makeDb({ students: { [CALLER]: { welcome_email_sent: true } } });

  const saveRes = makeRes();
  await saveHandler({ method: 'POST', body: {
    channels: { email: true },
    days_before: 3,
    category_prefs: { lab: true, homework: false, midterm: true, quiz: true, project: true },
    extra_reminder_days: { project: [1, 0], quiz: [5], other: [2] },
  } }, saveRes, makeDeps(db));
  assert.equal(saveRes.statusCode, 200);

  const res = await load(db);
  assert.deepEqual(res.body.data.extra_reminder_days, {
    ...EMPTY_CS61A, project: [1, 0], quiz: [5], other: [2],
  });
  assert.equal(res.body.data.days_before_deadline, 3);
});

test('a second save that unticks everything loads back as all empty', async () => {
  const db = makeDb({ students: { [CALLER]: { welcome_email_sent: true } } });
  const send = async (extras) => {
    const r = makeRes();
    await saveHandler({ method: 'POST', body: {
      channels: { email: true }, days_before: 3, extra_reminder_days: extras,
    } }, r, makeDeps(db));
    return r;
  };
  await send({ project: [1], lab: [2] });
  await send({});
  const res = await load(db);
  assert.deepEqual(res.body.data.extra_reminder_days, EMPTY_CS61A);
});

test('returns main_reminder_off, cleaned; [] when never saved', async () => {
  let res = await load(makeDb({ students: { [CALLER]: { main_reminder_off: ['project', 'postterm'] } } }));
  assert.deepEqual(res.body.data.main_reminder_off, ['project']);
  res = await load(makeDb({ students: { [CALLER]: { days_before_deadline: 3 } } }));
  assert.deepEqual(res.body.data.main_reminder_off, []);
});
