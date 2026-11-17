import test from 'node:test';
import assert from 'node:assert/strict';

import handler from './courses.js';

function makeRes() {
  const res = { statusCode: null, body: null };
  res.status = code => { res.statusCode = code; return res; };
  res.json = body => { res.body = body; return res; };
  return res;
}

function makeDb(role = 'instructor') {
  const docs = new Map();
  const profiles = new Map([['uid-1', { role }]]);
  const db = {
    collection(name) {
      return {
        doc(id) {
          const key = `${name}/${id}`;
          return {
            id,
            key,
            ref: { id, key },
            async get() {
              const value = name === 'user_profiles' ? profiles.get(id) : docs.get(key);
              return { exists: !!value, data: () => value };
            },
            async set(value, options = {}) {
              docs.set(key, options.merge ? { ...docs.get(key), ...value } : value);
            },
            async delete() {
              docs.delete(key);
            },
          };
        },
        where(field, _op, value) {
          let selected = [...docs.entries()]
            .filter(([key]) => key.startsWith(`${name}/`))
            .map(([key, data]) => ({
              id: key.slice(name.length + 1),
              data,
              ref: {
                id: key.slice(name.length + 1),
                key,
                async set(value, options = {}) {
                  docs.set(key, options.merge ? { ...docs.get(key), ...value } : value);
                },
              },
            }));
          selected = selected.filter(doc => doc.data[field] === value);
          return {
            where(nextField, _nextOp, nextValue) {
              selected = selected.filter(doc => doc.data[nextField] === nextValue);
              return this;
            },
            async get() {
              return { docs: selected.map(doc => ({ ...doc, data: () => doc.data })) };
            },
          };
        },
      };
    },
    batch() {
      const operations = [];
      return {
        set(ref, value) { operations.push(() => docs.set(ref.key, value)); },
        delete(ref) { operations.push(() => docs.delete(ref.key)); },
        async commit() { operations.forEach(operation => operation()); },
      };
    },
    _docs: docs,
    _profiles: profiles,
  };
  return db;
}

const authorized = async () => ({ authorized: true, uid: 'uid-1' });

// Instructor-facing errors must not mention the AI provider, server settings, or logs.
function assertNoInternals(message) {
  assert.doesNotMatch(
    message,
    /groq|GROQ_|\.env|server log|api key|credential|password|configured on this server|token|rate limit/i,
  );
}

// Stand-in for creating a course with a website URL whose page lists no assignments.
const emptyWebsiteImport = async url => ({
  course_url: url,
  pages_crawled: 1,
  pages_skipped: 0,
  candidates_reviewed: 0,
  assignments: [],
});

test('creating a course syncs its website when one is provided', async () => {
  const db = makeDb();
  const calls = [];
  const res = makeRes();
  await handler(
    {
      method: 'POST',
      body: {
        course_name: 'CS 61A',
        term: 'Fall 2026',
        gradescope_url: '12345',
        course_website_url: 'https://cs.example.edu/fa26/',
      },
    },
    res,
    {
      verifyUserAuth: authorized,
      getDb: () => db,
      importCourse: async id => {
        calls.push(`gradescope:${id}`);
        return {
          course_id: id,
          course_url: `https://www.gradescope.com/courses/${id}`,
          assignments: [{ id: '67890', title: 'Homework 1', due: '2026-10-01' }],
        };
      },
      importCourseWebsite: async (url, term) => {
        calls.push(`website:${url}:${term}`);
        return {
          course_url: url,
          pages_crawled: 1,
          pages_skipped: 0,
          candidates_reviewed: 1,
          assignments: [{
            id: '0123456789abcdef0123456789abcdef',
            title: 'Lab 1',
            due: '2026-09-02',
            html_url: url,
            source: 'website',
            resources: [],
          }],
        };
      },
    },
  );

  assert.equal(res.statusCode, 200);
  assert.deepEqual(calls.sort(), ['gradescope:12345', 'website:https://cs.example.edu/fa26/:Fall 2026']);
  assert.deepEqual(
    res.body.course.pending_assignments.map(assignment => [assignment.assignment_name, assignment.source]).sort(),
    [['Homework 1', 'gradescope'], ['Lab 1', 'website']],
  );
  assert.ok(res.body.course.course_website_synced_at);
});

test('Gradescope and website items for the same deadline are reviewed as one item', async () => {
  const db = makeDb();
  const websiteItem = (id, title, due) => ({
    id, title, due, html_url: 'https://cs.example.edu/fa26/', source: 'website', resources: [],
  });
  const createRes = makeRes();
  await handler(
    {
      method: 'POST',
      body: {
        course_name: 'CS 61C',
        term: 'Fall 2026',
        gradescope_url: '12345',
        course_website_url: 'https://cs.example.edu/fa26/',
      },
    },
    createRes,
    {
      verifyUserAuth: authorized,
      getDb: () => db,
      importCourse: async id => ({
        course_id: id,
        course_url: `https://www.gradescope.com/courses/${id}`,
        assignments: [
          { id: '201', title: 'Project 4 in Rust', due: '2026-12-07' },
          { id: '202', title: 'Project 4 in Python', due: '2026-12-07' },
          { id: '301', title: 'Discussion 3', due: '2026-09-18' },
        ],
      }),
      importCourseWebsite: async url => ({
        course_url: url,
        pages_crawled: 1,
        pages_skipped: 0,
        candidates_reviewed: 2,
        assignments: [
          websiteItem('aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa', 'Project 4', '2026-12-07'),
          websiteItem('bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb', 'Lab 8', null),
        ],
      }),
    },
  );
  assert.equal(createRes.statusCode, 200);
  const pending = createRes.body.course.pending_assignments;
  assert.deepEqual(
    pending.map(item => [item.assignment_name, item.source]),
    [['Project 4', 'gradescope'], ['Discussion 3', 'gradescope'], ['Lab 8', 'website']],
  );
  assert.deepEqual(pending[0].combined_titles, ['Project 4 in Rust', 'Project 4 in Python']);
  assert.deepEqual(pending[0].source_ids, ['201', '202', 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa']);

  // An item without a due date ("Lab 8") cannot be published.
  const courseId = createRes.body.course.course_id;
  const undatedRes = makeRes();
  await handler(
    {
      method: 'PUT',
      body: { action: 'finalize', course_id: courseId, approved_assignment_ids: pending.map(item => item.assignment_id) },
    },
    undatedRes,
    { verifyUserAuth: authorized, getDb: () => db },
  );
  assert.equal(undatedRes.statusCode, 400);
  assert.match(undatedRes.body.error, /Add a due date to “Lab 8”/);

  // Publishing keeps the record of what the combined item stands for.
  const finalizeRes = makeRes();
  await handler(
    {
      method: 'PUT',
      body: {
        action: 'finalize',
        course_id: courseId,
        approved_assignment_ids: pending.filter(item => item.due).map(item => item.assignment_id),
      },
    },
    finalizeRes,
    { verifyUserAuth: authorized, getDb: () => db },
  );
  assert.equal(finalizeRes.statusCode, 200);
  const saved = db._docs.get(`instructor_course_assignments/uid-1__${courseId}__201`);
  assert.deepEqual(saved.source_ids, ['201', '202', 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa']);

  // A later website-only sync does not propose deadlines Gradescope already covers.
  const syncRes = makeRes();
  await handler(
    { method: 'PUT', body: { action: 'sync_course_website', course_id: courseId } },
    syncRes,
    {
      verifyUserAuth: authorized,
      getDb: () => db,
      importCourseWebsite: async url => ({
        course_url: url,
        pages_crawled: 1,
        pages_skipped: 0,
        candidates_reviewed: 3,
        assignments: [
          websiteItem('cccccccccccccccccccccccccccccccc', 'Project 4', '2026-12-07'),
          websiteItem('bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb', 'Lab 8', null),
          websiteItem('dddddddddddddddddddddddddddddddd', 'Homework 9', '2026-11-17'),
        ],
      }),
    },
  );
  assert.equal(syncRes.statusCode, 200);
  // Project 4 is covered by Gradescope; Lab 8 was left out (no due date), so it is offered again.
  assert.deepEqual(syncRes.body.course.new_assignments.map(item => item.assignment_name), ['Lab 8', 'Homework 9']);
});

test('assignments cannot be added or edited without a due date', async () => {
  const db = makeDb();
  const createRes = makeRes();
  await handler({ method: 'POST', body: { course_name: 'CS 10' } }, createRes,
    { verifyUserAuth: authorized, getDb: () => db });
  const res = makeRes();
  await handler(
    { method: 'PUT', body: { action: 'add_assignment', course_id: createRes.body.course.course_id, assignment_name: 'Lab 1' } },
    res,
    { verifyUserAuth: authorized, getDb: () => db },
  );
  assert.equal(res.statusCode, 400);
  assert.match(res.body.error, /due date are required/);
});

test('the website’s own term decides which dates are in range, not a mistyped course term', async () => {
  const db = makeDb();
  const res = makeRes();
  await handler(
    {
      method: 'POST',
      body: { course_name: 'CS 61A', term: 'Spring 2029', course_website_url: 'https://cs61a.org/fa26/' },
    },
    res,
    {
      verifyUserAuth: authorized,
      getDb: () => db,
      importCourseWebsite: async url => ({
        course_url: url,
        pages_crawled: 1,
        pages_skipped: 0,
        candidates_reviewed: 1,
        website_term: 'Fall 2026',
        assignments: [{
          id: '0123456789abcdef0123456789abcdef',
          title: 'Homework 3',
          due: '2026-09-24',
          html_url: url,
          source: 'website',
          resources: [],
        }],
      }),
    },
  );
  assert.equal(res.statusCode, 200);
  assert.equal(res.body.course.course_website_term, 'Fall 2026');
  assert.deepEqual(res.body.course.pending_assignments[0].review_reasons, []);
});

test('creating a course without a website does not run the website importer', async () => {
  const db = makeDb();
  const res = makeRes();
  await handler(
    { method: 'POST', body: { course_name: 'CS 10' } },
    res,
    {
      verifyUserAuth: authorized,
      getDb: () => db,
      importCourseWebsite: async () => {
        throw new Error('The website importer should not run without a website URL.');
      },
    },
  );
  assert.equal(res.statusCode, 200);
  assert.equal(res.body.course.course_website_synced_at, undefined);
});

test('a course is not created when its website sync fails', async () => {
  const db = makeDb();
  const res = makeRes();
  await handler(
    { method: 'POST', body: { course_name: 'CS 61C', course_website_url: 'https://cs.example.edu/missing/' } },
    res,
    {
      verifyUserAuth: authorized,
      getDb: () => db,
      importCourseWebsite: async () => {
        throw new Error('WEBSITE_FETCH_ERROR: The starting course website URL returned HTTP 404.');
      },
    },
  );
  assert.equal(res.statusCode, 502);
  assert.match(res.body.error, /HTTP 404/);

  const listRes = makeRes();
  await handler({ method: 'GET' }, listRes, { verifyUserAuth: authorized, getDb: () => db });
  assert.equal(listRes.body.courses.length, 0);
});

test('course import is limited to instructor accounts', async () => {
  const db = makeDb('student');
  let importCalled = false;
  const res = makeRes();
  await handler(
    { method: 'POST', body: { course_name: 'CS 10', gradescope_url: 'https://www.gradescope.com/courses/12345' } },
    res,
    {
      verifyUserAuth: authorized,
      getDb: () => db,
      importCourse: async () => { importCalled = true; },
    },
  );
  assert.equal(res.statusCode, 403);
  assert.equal(importCalled, false);
});

test('course import validates the ID and stages assignments for instructor review', async () => {
  const db = makeDb();
  let importedId;
  const res = makeRes();
  await handler(
    {
      method: 'POST',
      body: {
        course_name: 'CS 10',
        term: 'Fall 2026',
        description: 'This legacy field is ignored.',
        gradescope_url: '12345',
        course_website_url: 'https://cs.example.edu/course',
      },
    },
    res,
    {
      verifyUserAuth: authorized,
      getDb: () => db, importCourseWebsite: emptyWebsiteImport,
      importCourse: async id => {
        importedId = id;
        return {
          course_id: id,
          course_name: 'CS 10',
          course_url: 'https://www.gradescope.com/courses/12345',
          assignments: [{ id: '67890', title: 'Homework 1', due: '2026-10-30T23:59:00Z' }],
        };
      },
    },
  );
  assert.equal(res.statusCode, 200);
  assert.equal(importedId, '12345');
  assert.equal(res.body.course.status, 'pending_review');
  assert.equal(res.body.course.pending_assignment_count, 1);
  assert.equal(res.body.course.course_name, 'CS 10');
  assert.equal(res.body.course.term, 'Fall 2026');
  assert.equal('description' in res.body.course, false);
  const courseId = res.body.course.course_id;
  assert.notEqual(courseId, '12345');
  assert.equal('description' in db._docs.get(`instructor_courses/uid-1__${courseId}`), false);
  assert.equal(res.body.course.course_website_url, 'https://cs.example.edu/course');
  assert.equal(res.body.course.pending_assignments[0].assignment_name, 'Homework 1');
  assert.ok(db._docs.has(`instructor_courses/uid-1__${courseId}`));
  assert.ok(db._docs.has(`instructor_course_assignment_reviews/uid-1__${courseId}__67890`));
  assert.equal(db._docs.has(`instructor_course_assignments/uid-1__${courseId}__67890`), false);
});

test('course descriptions are ignored when creating a course', async () => {
  const res = makeRes();
  await handler(
    {
      method: 'POST',
      body: {
        course_name: 'CS 10',
        description: 'Legacy description',
      },
    },
    res,
    { verifyUserAuth: authorized, getDb: () => makeDb() },
  );
  assert.equal(res.statusCode, 200);
  assert.equal('description' in res.body.course, false);
});

test('instructor can create a course without platform IDs and add assignments during review', async () => {
  const db = makeDb();
  const createRes = makeRes();
  await handler(
    { method: 'POST', body: { course_name: 'Independent Course' } },
    createRes,
    { verifyUserAuth: authorized, getDb: () => db },
  );
  assert.equal(createRes.statusCode, 200);
  assert.equal(createRes.body.course.status, 'pending_review');
  assert.deepEqual(createRes.body.course.pending_assignments, []);
  const courseId = createRes.body.course.course_id;

  const addRes = makeRes();
  await handler(
    {
      method: 'PUT',
      body: { action: 'add_assignment', course_id: courseId, assignment_name: 'Project 1', due: '2026-11-15' },
    },
    addRes,
    { verifyUserAuth: authorized, getDb: () => db },
  );
  assert.equal(addRes.statusCode, 200);

  const discardRes = makeRes();
  await handler(
    {
      method: 'PUT',
      body: { action: 'add_assignment', due: '2026-10-01', course_id: courseId, assignment_name: 'Discarded draft' },
    },
    discardRes,
    { verifyUserAuth: authorized, getDb: () => db },
  );
  const removeDraftRes = makeRes();
  await handler(
    {
      method: 'PUT',
      body: {
        action: 'remove_assignment',
        course_id: courseId,
        assignment_id: discardRes.body.assignment.assignment_id,
      },
    },
    removeDraftRes,
    { verifyUserAuth: authorized, getDb: () => db },
  );
  assert.equal(removeDraftRes.statusCode, 200);

  const updateReviewRes = makeRes();
  await handler(
    {
      method: 'PUT',
      body: {
        action: 'update_assignment',
        course_id: courseId,
        assignment_id: addRes.body.assignment.assignment_id,
        assignment_name: 'Project 1 revised',
        due: '2026-11-20',
        resources: [{ resource_name: 'Lecture notes', link: 'https://example.edu/notes' }],
      },
    },
    updateReviewRes,
    { verifyUserAuth: authorized, getDb: () => db },
  );
  assert.equal(updateReviewRes.statusCode, 200);

  const listRes = makeRes();
  await handler(
    { method: 'GET' },
    listRes,
    { verifyUserAuth: authorized, getDb: () => db },
  );
  assert.equal(listRes.body.courses[0].pending_assignments[0].assignment_name, 'Project 1 revised');
  assert.equal(listRes.body.courses[0].pending_assignments[0].due, '2026-11-20');
  assert.deepEqual(listRes.body.courses[0].pending_assignments[0].resources, [
    { resource_name: 'Lecture notes', resource_type: 'Link', link: 'https://example.edu/notes' },
  ]);
  assert.equal(listRes.body.courses[0].pending_assignments[0].source, 'instructor');

  const finalizeRes = makeRes();
  await handler(
    {
      method: 'PUT',
      body: {
        action: 'finalize',
        course_id: courseId,
        approved_assignment_ids: [addRes.body.assignment.assignment_id],
      },
    },
    finalizeRes,
    { verifyUserAuth: authorized, getDb: () => db },
  );
  assert.equal(finalizeRes.statusCode, 200);
  assert.equal(finalizeRes.body.course.assignments[0].source, 'instructor');
  assert.deepEqual(finalizeRes.body.course.assignments[0].resources, [
    { resource_name: 'Lecture notes', resource_type: 'Link', link: 'https://example.edu/notes' },
  ]);
});

test('instructor can add and remove assignments after course review', async () => {
  const db = makeDb();
  const createRes = makeRes();
  await handler(
    { method: 'POST', body: { course_name: 'Independent Course' } },
    createRes,
    { verifyUserAuth: authorized, getDb: () => db },
  );
  const courseId = createRes.body.course.course_id;
  const finalizeRes = makeRes();
  await handler(
    { method: 'PUT', body: { action: 'finalize', course_id: courseId, approved_assignment_ids: [] } },
    finalizeRes,
    { verifyUserAuth: authorized, getDb: () => db },
  );
  assert.equal(finalizeRes.statusCode, 200);

  const addRes = makeRes();
  await handler(
    { method: 'PUT', body: { action: 'add_assignment', due: '2026-10-01', course_id: courseId, assignment_name: 'Reading 1' } },
    addRes,
    { verifyUserAuth: authorized, getDb: () => db },
  );
  assert.equal(addRes.statusCode, 200);

  const updateRes = makeRes();
  await handler(
    {
      method: 'PUT',
      body: {
        action: 'update_assignment',
        course_id: courseId,
        assignment_id: addRes.body.assignment.assignment_id,
        assignment_name: 'Reading 1 revised',
        due: '2026-12-01',
        resources: [{ resource_name: 'Review sheet', resource_type: 'Reading', link: 'https://example.edu/review' }],
      },
    },
    updateRes,
    { verifyUserAuth: authorized, getDb: () => db },
  );
  assert.equal(updateRes.statusCode, 200);

  const updatedListRes = makeRes();
  await handler(
    { method: 'GET' },
    updatedListRes,
    { verifyUserAuth: authorized, getDb: () => db },
  );
  assert.equal(updatedListRes.body.courses[0].assignments[0].assignment_name, 'Reading 1 revised');
  assert.equal(updatedListRes.body.courses[0].assignments[0].due, '2026-12-01');
  assert.deepEqual(updatedListRes.body.courses[0].assignments[0].resources, [
    { resource_name: 'Review sheet', resource_type: 'Reading', link: 'https://example.edu/review' },
  ]);

  const removeRes = makeRes();
  await handler(
    {
      method: 'PUT',
      body: {
        action: 'remove_assignment',
        course_id: courseId,
        assignment_id: addRes.body.assignment.assignment_id,
      },
    },
    removeRes,
    { verifyUserAuth: authorized, getDb: () => db },
  );
  assert.equal(removeRes.statusCode, 200);

  const listRes = makeRes();
  await handler(
    { method: 'GET' },
    listRes,
    { verifyUserAuth: authorized, getDb: () => db },
  );
  assert.deepEqual(listRes.body.courses[0].assignments, []);
});

test('assignment edits are routed by assignment ID when the action field is omitted', async () => {
  const db = makeDb();
  const createRes = makeRes();
  await handler(
    { method: 'POST', body: { course_name: 'Independent Course' } },
    createRes,
    { verifyUserAuth: authorized, getDb: () => db },
  );
  const courseId = createRes.body.course.course_id;
  const addRes = makeRes();
  await handler(
    {
      method: 'PUT',
      body: { action: 'add_assignment', due: '2026-10-01', course_id: courseId, assignment_name: 'Homework 1' },
    },
    addRes,
    { verifyUserAuth: authorized, getDb: () => db },
  );

  const updateRes = makeRes();
  await handler(
    {
      method: 'PUT',
      body: {
        course_id: courseId,
        assignment_id: addRes.body.assignment.assignment_id,
        assignment_name: 'Homework 1 Revised',
        due: '2026-11-15',
        resources: [],
      },
    },
    updateRes,
    { verifyUserAuth: authorized, getDb: () => db },
  );
  assert.equal(updateRes.statusCode, 200);

  const listRes = makeRes();
  await handler(
    { method: 'GET' },
    listRes,
    { verifyUserAuth: authorized, getDb: () => db },
  );
  assert.equal(listRes.body.courses[0].pending_assignments[0].assignment_name, 'Homework 1 Revised');
});

test('each Gradescope course can be connected to only one course', async () => {
  const db = makeDb();
  db._profiles.set('uid-2', { role: 'instructor' });
  const otherInstructor = async () => ({ authorized: true, uid: 'uid-2' });
  let gradescopeCalls = 0;
  const importCourse = async id => {
    gradescopeCalls += 1;
    return { course_id: id, assignments: [{ id: '67890', title: 'Homework 1', due: '2026-10-01' }] };
  };
  const create = async (verifyUserAuth, body) => {
    const res = makeRes();
    await handler({ method: 'POST', body }, res, { verifyUserAuth, getDb: () => db, importCourse });
    return res;
  };

  const first = await create(authorized, { course_name: 'CS 10 - Fall', gradescope_url: '12345' });
  assert.equal(first.statusCode, 200);
  assert.equal(gradescopeCalls, 1);

  // Neither the same instructor nor anyone else can reuse it; both see the same message,
  // which does not say whose course it is.
  const inUse = 'This Gradescope Course ID is already connected to a course in AutoRemind. If you think this is a mistake, please contact the AutoRemind team.';
  const again = await create(authorized, { course_name: 'CS 10 - Spring', gradescope_url: '12345' });
  assert.equal(again.statusCode, 409);
  assert.equal(again.body.error, inUse);
  const other = await create(otherInstructor, { course_name: 'My CS 10', gradescope_url: '12345' });
  assert.equal(other.statusCode, 409);
  assert.equal(other.body.error, inUse);

  // Blocked requests never contact Gradescope, and create nothing.
  assert.equal(gradescopeCalls, 1);
  const courseDocs = [...db._docs.keys()].filter(key => key.startsWith('instructor_courses/'));
  assert.equal(courseDocs.length, 1);

  // A different Gradescope course is fine.
  const otherCourse = await create(otherInstructor, { course_name: 'CS 61A', gradescope_url: '54321' });
  assert.equal(otherCourse.statusCode, 200);

  // Editing a course to use a Gradescope ID another course has is blocked too; nothing changes.
  const editRes = makeRes();
  await handler(
    {
      method: 'PUT',
      body: { course_id: otherCourse.body.course.course_id, course_name: 'CS 61A', gradescope_url: '12345' },
    },
    editRes,
    { verifyUserAuth: otherInstructor, getDb: () => db, importCourse },
  );
  assert.equal(editRes.statusCode, 409);
  assert.equal(editRes.body.error, inUse);
  assert.equal(
    db._docs.get(`instructor_courses/uid-2__${otherCourse.body.course.course_id}`).gradescope_course_id,
    '54321',
  );

  // Re-saving a course with its own Gradescope ID is not a conflict.
  const resaveRes = makeRes();
  await handler(
    {
      method: 'PUT',
      body: { course_id: first.body.course.course_id, course_name: 'CS 10', gradescope_url: '12345' },
    },
    resaveRes,
    { verifyUserAuth: authorized, getDb: () => db, importCourse },
  );
  assert.equal(resaveRes.statusCode, 200);

  // Archived courses keep their Gradescope course.
  const archiveRes = makeRes();
  await handler(
    { method: 'PUT', body: { action: 'archive', course_id: first.body.course.course_id } },
    archiveRes,
    { verifyUserAuth: authorized, getDb: () => db },
  );
  assert.equal(archiveRes.statusCode, 200);
  assert.equal((await create(otherInstructor, { course_name: 'CS 10', gradescope_url: '12345' })).statusCode, 409);

  // Deleting the course frees it.
  const deleteRes = makeRes();
  await handler(
    { method: 'DELETE', body: { course_id: first.body.course.course_id } },
    deleteRes,
    { verifyUserAuth: authorized, getDb: () => db },
  );
  assert.equal(deleteRes.statusCode, 200);
  assert.equal((await create(otherInstructor, { course_name: 'CS 10', gradescope_url: '12345' })).statusCode, 200);
});

test('course website URL must use HTTP or HTTPS', async () => {
  const res = makeRes();
  await handler(
    {
      method: 'POST',
      body: {
        course_name: 'CS 10',
        course_website_url: 'javascript:alert(1)',
      },
    },
    res,
    { verifyUserAuth: authorized, getDb: () => makeDb(), importCourseWebsite: emptyWebsiteImport },
  );
  assert.equal(res.statusCode, 400);
  assert.match(res.body.error, /valid course website URL/i);
});

test('instructor can edit course name without changing staged assignments', async () => {
  const db = makeDb();
  const createRes = makeRes();
  await handler(
    {
      method: 'POST',
      body: {
        course_name: 'CS 10',
        term: 'Fall 2026',
        gradescope_url: '12345',
        course_website_url: 'https://cs.example.edu/course',
      },
    },
    createRes,
    {
      verifyUserAuth: authorized,
      getDb: () => db, importCourseWebsite: emptyWebsiteImport,
      importCourse: async id => ({
        course_id: id,
        course_name: 'CS 10',
        course_url: 'https://www.gradescope.com/courses/12345',
        assignments: [{ id: '67890', title: 'Homework 1', due: '2026-10-30T23:59:00Z' }],
      }),
    },
  );

  const courseId = createRes.body.course.course_id;
  let importCalled = false;
  const res = makeRes();
  await handler(
    {
      method: 'PUT',
      body: {
        course_id: courseId,
        course_name: 'Intro CS',
        term: 'Spring 2027',
        gradescope_url: '12345',
        bcourses_url: '7KN4P5',
        course_website_url: 'https://cs.example.edu/course',
      },
    },
    res,
    {
      verifyUserAuth: authorized,
      getDb: () => db,
      importCourse: async () => {
        importCalled = true;
        throw new Error('Gradescope should not be imported when course sources are unchanged.');
      },
    },
  );
  assert.equal(importCalled, false);
  assert.equal(res.statusCode, 200);
  assert.equal(res.body.course.course_name, 'Intro CS');
  assert.equal(res.body.course.term, 'Spring 2027');
  assert.equal('description' in res.body.course, false);
  assert.equal(res.body.course.gradescope_course_id, '12345');
  assert.equal(res.body.course.course_website_url, 'https://cs.example.edu/course');
  assert.equal(res.body.course.status, 'pending_review');
  assert.ok(db._docs.has(`instructor_course_assignment_reviews/uid-1__${courseId}__67890`));

  const clearSourcesRes = makeRes();
  await handler(
    {
      method: 'PUT',
      body: {
        course_id: courseId,
        course_name: 'Intro CS',
        term: 'Spring 2027',
        gradescope_url: '',
        course_website_url: '',
      },
    },
    clearSourcesRes,
    { verifyUserAuth: authorized, getDb: () => db },
  );
  assert.equal(clearSourcesRes.statusCode, 200);
  assert.equal(clearSourcesRes.body.course.gradescope_course_id, null);
  assert.equal(clearSourcesRes.body.course.gradescope_url, '');
  assert.equal(clearSourcesRes.body.course.course_website_url, '');
});

test('editing a course syncs only the source whose identifier changed', async () => {
  const db = makeDb();
  const createRes = makeRes();
  await handler(
    {
      method: 'POST',
      body: {
        course_name: 'CS 61A',
        term: 'Fall 2026',
        gradescope_url: '12345',
        course_website_url: 'https://cs.example.edu/fa26/',
      },
    },
    createRes,
    {
      verifyUserAuth: authorized,
      getDb: () => db, importCourseWebsite: emptyWebsiteImport,
      importCourse: async id => ({ course_id: id, course_url: '', assignments: [] }),
    },
  );
  const courseId = createRes.body.course.course_id;
  const calls = [];
  const deps = {
    verifyUserAuth: authorized,
    getDb: () => db,
    importCourse: async id => {
      calls.push(`gradescope:${id}`);
      return { course_id: id, course_url: `https://www.gradescope.com/courses/${id}`, assignments: [] };
    },
    importCourseWebsite: async url => {
      calls.push(`website:${url}`);
      return {
        course_url: url,
        pages_crawled: 1,
        pages_skipped: 0,
        candidates_reviewed: 1,
        assignments: [{
          id: '0123456789abcdef0123456789abcdef',
          title: 'Homework 1',
          due: '2026-09-03',
          html_url: url,
          source: 'website',
          resources: [],
        }],
      };
    },
  };
  const edit = async changes => {
    const res = makeRes();
    await handler(
      {
        method: 'PUT',
        body: {
          course_id: courseId,
          course_name: 'CS 61A',
          term: 'Fall 2026',
          gradescope_url: '12345',
          course_website_url: 'https://cs.example.edu/fa26/',
          ...changes,
        },
      },
      res,
      deps,
    );
    return res;
  };

  // Only the name changes: nothing syncs.
  const renamed = await edit({ course_name: 'CS 61A: SICP' });
  assert.equal(renamed.statusCode, 200);
  assert.deepEqual(calls, []);

  // Only the website changes: only the website syncs.
  const newWebsite = await edit({ course_website_url: 'https://cs.example.edu/fa26/schedule' });
  assert.equal(newWebsite.statusCode, 200);
  assert.deepEqual(calls, ['website:https://cs.example.edu/fa26/schedule']);
  assert.equal(newWebsite.body.course.new_assignments.length, 1);
  assert.deepEqual(newWebsite.body.sync_summary, { website: { found: 1 } });
  assert.deepEqual(renamed.body.sync_summary, {});
  assert.ok(newWebsite.body.course.course_website_synced_at);

  // Saving the same values again does not sync.
  calls.length = 0;
  await edit({ course_website_url: 'https://cs.example.edu/fa26/schedule' });
  assert.deepEqual(calls, []);

  // Only the Gradescope ID changes: only Gradescope syncs.
  const newGradescope = await edit({
    gradescope_url: '67890',
    course_website_url: 'https://cs.example.edu/fa26/schedule',
  });
  assert.equal(newGradescope.statusCode, 200);
  assert.deepEqual(calls, ['gradescope:67890']);

  // Both change: both sync, and assignments from both are staged.
  calls.length = 0;
  const bothChanged = await edit({
    gradescope_url: '24680',
    course_website_url: 'https://cs.example.edu/fa26/assignments',
  });
  assert.equal(bothChanged.statusCode, 200);
  assert.deepEqual(calls.sort(), [
    'gradescope:24680',
    'website:https://cs.example.edu/fa26/assignments',
  ]);
  assert.equal(bothChanged.body.course.gradescope_course_id, '24680');
  assert.equal(bothChanged.body.course.course_website_url, 'https://cs.example.edu/fa26/assignments');
});

test('a failed automatic sync does not save the changed course source', async () => {
  const db = makeDb();
  const createRes = makeRes();
  await handler(
    { method: 'POST', body: { course_name: 'CS 61C', course_website_url: 'https://cs.example.edu/old/' } },
    createRes,
    { verifyUserAuth: authorized, getDb: () => db, importCourseWebsite: emptyWebsiteImport },
  );
  const courseId = createRes.body.course.course_id;
  const res = makeRes();
  await handler(
    {
      method: 'PUT',
      body: { course_id: courseId, course_name: 'CS 61C', course_website_url: 'https://cs.example.edu/new/' },
    },
    res,
    {
      verifyUserAuth: authorized,
      getDb: () => db,
      importCourseWebsite: async () => {
        throw new Error('WEBSITE_FETCH_ERROR: The starting course website URL returned HTTP 404.');
      },
    },
  );
  assert.equal(res.statusCode, 502);
  assert.match(res.body.error, /HTTP 404/);

  const listRes = makeRes();
  await handler({ method: 'GET' }, listRes, { verifyUserAuth: authorized, getDb: () => db });
  assert.equal(listRes.body.courses[0].course_website_url, 'https://cs.example.edu/old/');
});

test('editing course sources syncs only new assignments into review', async () => {
  const db = makeDb();
  const importCourse = async id => ({
    course_id: id,
    course_url: `https://www.gradescope.com/courses/${id}`,
    assignments: [{ id: 'existing', title: 'Original Homework', due: '2026-10-01' }],
  });
  const createRes = makeRes();
  await handler(
    { method: 'POST', body: { course_name: 'CS 10', gradescope_url: '12345' } },
    createRes,
    { verifyUserAuth: authorized, getDb: () => db, importCourse },
  );
  const courseId = createRes.body.course.course_id;
  const finalizeRes = makeRes();
  await handler(
    {
      method: 'PUT',
      body: { action: 'finalize', course_id: courseId, approved_assignment_ids: ['existing'] },
    },
    finalizeRes,
    { verifyUserAuth: authorized, getDb: () => db },
  );

  const editRes = makeRes();
  await handler(
    {
      method: 'PUT',
      body: {
        course_id: courseId,
        course_name: 'Intro CS',
        term: 'Spring 2027',
        gradescope_url: '54321',
        course_website_url: 'https://cs.example.edu',
      },
    },
    editRes,
    {
      verifyUserAuth: authorized,
      getDb: () => db,
      importCourse: async id => ({
        course_id: id,
        course_url: `https://www.gradescope.com/courses/${id}`,
        assignments: [
          { id: 'existing', title: 'Renamed by Gradescope', due: '2026-10-01' },
          { id: 'new-assignment', title: 'New Homework', due: '2026-10-01' },
        ],
      }),
      // The website was added in this edit, so it is synced too.
      importCourseWebsite: async url => ({
        course_url: url,
        pages_crawled: 1,
        pages_skipped: 0,
        candidates_reviewed: 0,
        assignments: [],
      }),
    },
  );
  assert.equal(editRes.statusCode, 200);
  assert.equal(editRes.body.course.course_name, 'Intro CS');
  assert.equal(editRes.body.course.gradescope_course_id, '54321');
  assert.equal(editRes.body.course.course_website_url, 'https://cs.example.edu/');
  assert.deepEqual(editRes.body.course.new_assignments.map(assignment => assignment.assignment_id), ['new-assignment']);

  const listRes = makeRes();
  await handler({ method: 'GET' }, listRes, { verifyUserAuth: authorized, getDb: () => db });
  assert.equal(listRes.body.courses[0].assignments[0].assignment_name, 'Original Homework');
  assert.deepEqual(listRes.body.courses[0].new_assignments.map(assignment => assignment.assignment_id), ['new-assignment']);

  const updateSyncedRes = makeRes();
  await handler(
    {
      method: 'PUT',
      body: {
        action: 'update_synced_assignment',
        course_id: courseId,
        assignment_id: 'new-assignment',
        assignment_name: 'New Homework (edited)',
        due: '2027-01-15',
        resources: [{
          resource_name: 'Study guide',
          resource_type: 'Reading',
          link: 'https://example.edu/study-guide',
        }],
      },
    },
    updateSyncedRes,
    { verifyUserAuth: authorized, getDb: () => db },
  );
  assert.equal(updateSyncedRes.statusCode, 200);

  const updatedStagedListRes = makeRes();
  await handler(
    { method: 'GET' },
    updatedStagedListRes,
    { verifyUserAuth: authorized, getDb: () => db },
  );
  assert.equal(
    updatedStagedListRes.body.courses[0].new_assignments[0].assignment_name,
    'New Homework (edited)',
  );
  assert.equal(updatedStagedListRes.body.courses[0].new_assignments[0].due, '2027-01-15');
  assert.deepEqual(updatedStagedListRes.body.courses[0].new_assignments[0].resources, [{
    resource_name: 'Study guide',
    resource_type: 'Reading',
    link: 'https://example.edu/study-guide',
  }]);

  const reviewRes = makeRes();
  await handler(
    {
      method: 'PUT',
      body: {
        action: 'review_synced_assignments',
        course_id: courseId,
        approved_assignment_ids: ['new-assignment'],
      },
    },
    reviewRes,
    { verifyUserAuth: authorized, getDb: () => db },
  );
  assert.equal(reviewRes.statusCode, 200);
  const reviewedListRes = makeRes();
  await handler({ method: 'GET' }, reviewedListRes, { verifyUserAuth: authorized, getDb: () => db });
  assert.deepEqual(
    reviewedListRes.body.courses[0].assignments.map(assignment => assignment.assignment_id).sort(),
    ['existing', 'new-assignment'],
  );
  assert.deepEqual(reviewedListRes.body.courses[0].new_assignments, []);
});

test('instructor can manually sync Gradescope and stage only new assignments', async () => {
  const db = makeDb();
  const createRes = makeRes();
  await handler(
    { method: 'POST', body: { course_name: 'CS 10', gradescope_url: '12345' } },
    createRes,
    {
      verifyUserAuth: authorized,
      getDb: () => db,
      importCourse: async id => ({
        course_id: id,
        assignments: [{ id: 'existing', title: 'Homework 1', due: '2026-10-01' }],
      }),
    },
  );
  const courseId = createRes.body.course.course_id;
  const finalizeRes = makeRes();
  await handler(
    {
      method: 'PUT',
      body: { action: 'finalize', course_id: courseId, approved_assignment_ids: ['existing'] },
    },
    finalizeRes,
    { verifyUserAuth: authorized, getDb: () => db },
  );

  const syncRes = makeRes();
  await handler(
    { method: 'PUT', body: { action: 'sync_gradescope', course_id: courseId } },
    syncRes,
    {
      verifyUserAuth: authorized,
      getDb: () => db,
      importCourse: async id => ({
        course_id: id,
        assignments: [
          { id: 'existing', title: 'Homework 1', due: '2026-10-01' },
          { id: 'new', title: 'Homework 2', due: '2026-10-01' },
        ],
      }),
    },
  );
  assert.equal(syncRes.statusCode, 200);
  assert.equal(syncRes.body.course.new_assignment_count, 1);
  assert.deepEqual(syncRes.body.course.new_assignments.map(assignment => assignment.assignment_id), ['new']);

  const listRes = makeRes();
  await handler({ method: 'GET' }, listRes, { verifyUserAuth: authorized, getDb: () => db });
  assert.deepEqual(listRes.body.courses[0].assignments.map(assignment => assignment.assignment_id), ['existing']);
  assert.deepEqual(listRes.body.courses[0].new_assignments.map(assignment => assignment.assignment_id), ['new']);
});

test('course website sync stages verified assignments for instructor review', async () => {
  const db = makeDb();
  const createRes = makeRes();
  await handler(
    {
      method: 'POST',
      body: {
        course_name: 'CS 10',
        term: 'Fall 2026',
        course_website_url: 'https://cs.example.edu/',
      },
    },
    createRes,
    { verifyUserAuth: authorized, getDb: () => db, importCourseWebsite: emptyWebsiteImport },
  );
  const courseId = createRes.body.course.course_id;
  const importedAssignments = [{
    id: '0123456789abcdef0123456789abcdef',
    title: 'Homework 1',
    due: '2026-09-15',
    html_url: 'https://cs.example.edu/hw1',
    source: 'website',
    resources: [{
      resource_name: 'Starter code',
      resource_type: 'Link',
      link: 'https://cs.example.edu/hw1.zip',
    }],
  }];
  const syncRes = makeRes();
  await handler(
    { method: 'PUT', body: { action: 'sync_course_website', course_id: courseId } },
    syncRes,
    {
      verifyUserAuth: authorized,
      getDb: () => db,
      importCourseWebsite: async (url, term) => {
        assert.equal(url, 'https://cs.example.edu/');
        assert.equal(term, 'Fall 2026');
        return {
          course_url: url,
          pages_crawled: 12,
          pages_skipped: 2,
          candidates_reviewed: 4,
          assignments: importedAssignments,
        };
      },
    },
  );
  assert.equal(syncRes.statusCode, 200);
  assert.equal(syncRes.body.course.new_assignment_count, 1);
  assert.equal(syncRes.body.course.course_website_pages_crawled, 12);
  assert.equal(syncRes.body.course.course_website_pages_skipped, 2);
  assert.equal(syncRes.body.course.gradescope_course_id, null);
  assert.equal(syncRes.body.course.gradescope_url, '');

  const listRes = makeRes();
  await handler({ method: 'GET' }, listRes, { verifyUserAuth: authorized, getDb: () => db });
  assert.equal(listRes.body.courses[0].status, 'pending_review');
  assert.equal(listRes.body.courses[0].pending_assignments[0].assignment_name, 'Homework 1');
  assert.equal(listRes.body.courses[0].pending_assignments[0].source, 'website');

  const finalizeRes = makeRes();
  await handler(
    {
      method: 'PUT',
      body: {
        action: 'finalize',
        course_id: courseId,
        approved_assignment_ids: [importedAssignments[0].id],
      },
    },
    finalizeRes,
    { verifyUserAuth: authorized, getDb: () => db },
  );
  assert.equal(finalizeRes.statusCode, 200);
  assert.equal(finalizeRes.body.course.assignments[0].source, 'website');
  assert.deepEqual(finalizeRes.body.course.assignments[0].resources, importedAssignments[0].resources);

  const secondAssignment = {
    id: 'fedcba9876543210fedcba9876543210',
    title: 'Homework 2',
    due: null,
    html_url: 'https://cs.example.edu/hw2',
    source: 'website',
    resources: [],
  };
  const resyncRes = makeRes();
  await handler(
    { method: 'PUT', body: { action: 'sync_course_website', course_id: courseId } },
    resyncRes,
    {
      verifyUserAuth: authorized,
      getDb: () => db,
      importCourseWebsite: async url => ({
        course_url: url,
        pages_crawled: 12,
        candidates_reviewed: 5,
        assignments: [...importedAssignments, secondAssignment],
      }),
    },
  );
  assert.equal(resyncRes.statusCode, 200);
  assert.equal(resyncRes.body.course.new_assignment_count, 1);
  assert.equal(resyncRes.body.course.new_assignments[0].assignment_name, 'Homework 2');
});

test('assignments sharing a name with existing ones are still shown for review', async () => {
  const db = makeDb();
  const createRes = makeRes();
  await handler(
    {
      method: 'POST',
      body: { course_name: 'CS 61A', term: 'Fall 2026', course_website_url: 'https://cs.example.edu/' },
    },
    createRes,
    { verifyUserAuth: authorized, getDb: () => db, importCourseWebsite: emptyWebsiteImport },
  );
  const courseId = createRes.body.course.course_id;
  const syncWith = async assignment => {
    const res = makeRes();
    await handler(
      { method: 'PUT', body: { action: 'sync_course_website', course_id: courseId } },
      res,
      {
        verifyUserAuth: authorized,
        getDb: () => db,
        importCourseWebsite: async url => ({
          course_url: url,
          pages_crawled: 1,
          pages_skipped: 0,
          candidates_reviewed: 1,
          assignments: [assignment],
        }),
      },
    );
    return res;
  };

  // Listed before release: no assignment page yet, so the homepage stands in.
  const before = await syncWith({
    id: 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
    title: 'Homework 8: Gleam Data',
    due: '2026-11-12',
    html_url: 'https://cs.example.edu/',
    source: 'website',
    resources: [],
  });
  assert.equal(before.body.course.new_assignment_count, 1);

  // Same name, different item (new link, new due date): staged for the instructor to review.
  const after = await syncWith({
    id: 'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb',
    title: 'Homework 8: Gleam Data',
    due: '2026-11-19',
    html_url: 'https://cs.example.edu/hw/hw08/',
    source: 'website',
    resources: [],
  });
  assert.equal(after.statusCode, 200);
  assert.equal(after.body.course.new_assignment_count, 1);

  // Only the exact same item (same ID) from an earlier sync is skipped.
  const again = await syncWith({
    id: 'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb',
    title: 'Homework 8: Gleam Data',
    due: '2026-11-19',
    html_url: 'https://cs.example.edu/hw/hw08/',
    source: 'website',
    resources: [],
  });
  assert.equal(again.body.course.new_assignment_count, 0);
});

test('course website sync requires a configured course website URL', async () => {
  const db = makeDb();
  const createRes = makeRes();
  await handler(
    { method: 'POST', body: { course_name: 'CS 10' } },
    createRes,
    { verifyUserAuth: authorized, getDb: () => db },
  );
  const syncRes = makeRes();
  let importCalled = false;
  await handler(
    { method: 'PUT', body: { action: 'sync_course_website', course_id: createRes.body.course.course_id } },
    syncRes,
    {
      verifyUserAuth: authorized,
      getDb: () => db,
      importCourseWebsite: async () => { importCalled = true; },
    },
  );
  assert.equal(syncRes.statusCode, 400);
  assert.equal(importCalled, false);
});

test('incomplete website crawls do not save partial assignment results', async () => {
  const db = makeDb();
  const createRes = makeRes();
  await handler(
    {
      method: 'POST',
      body: { course_name: 'CS 10', course_website_url: 'https://cs.example.edu/' },
    },
    createRes,
    { verifyUserAuth: authorized, getDb: () => db, importCourseWebsite: emptyWebsiteImport },
  );
  const courseId = createRes.body.course.course_id;
  // Creating the course ran the first website sync.
  const firstSyncedAt = db._docs.get(`instructor_courses/uid-1__${courseId}`).course_website_synced_at;
  assert.ok(firstSyncedAt);
  const syncRes = makeRes();
  await handler(
    { method: 'PUT', body: { action: 'sync_course_website', course_id: courseId } },
    syncRes,
    {
      verifyUserAuth: authorized,
      getDb: () => db,
      importCourseWebsite: async () => {
        throw new Error('WEBSITE_CRAWL_LIMIT_ERROR: crawl limit reached');
      },
    },
  );
  assert.equal(syncRes.statusCode, 422);
  // The failed sync records nothing: the last successful sync time is unchanged.
  assert.equal(
    db._docs.get(`instructor_courses/uid-1__${courseId}`).course_website_synced_at,
    firstSyncedAt,
  );
  assert.equal(
    [...db._docs.keys()].some(key => key.startsWith('instructor_course_assignment_reviews/')),
    false,
  );
});

test('website fetch failures explain that the source could not be reached', async () => {
  const db = makeDb();
  const createRes = makeRes();
  await handler(
    {
      method: 'POST',
      body: { course_name: 'CS 10', course_website_url: 'https://cs.example.edu/' },
    },
    createRes,
    { verifyUserAuth: authorized, getDb: () => db, importCourseWebsite: emptyWebsiteImport },
  );
  const syncRes = makeRes();
  await handler(
    {
      method: 'PUT',
      body: { action: 'sync_course_website', course_id: createRes.body.course.course_id },
    },
    syncRes,
    {
      verifyUserAuth: authorized,
      getDb: () => db,
      importCourseWebsite: async () => {
        throw new Error('WEBSITE_FETCH_ERROR: A course page could not be retrieved. The page returned HTTP 403.');
      },
    },
  );
  assert.equal(syncRes.statusCode, 502);
  assert.match(syncRes.body.error, /HTTP 403/);
  assert.match(syncRes.body.error, /website is public and the link is correct/);
  assertNoInternals(syncRes.body.error);
});

test('AI service failures show instructors a generic message without internals', async () => {
  for (const [marker, expectedMessage] of [
    [
      'WEBSITE_IMPORT_GROQ_AUTH_ERROR: HTTP 401',
      /isn’t available right now/,
    ],
    [
      'WEBSITE_IMPORT_GROQ_MODEL_ERROR: HTTP 404',
      /isn’t available right now/,
    ],
    [
      'WEBSITE_IMPORT_LLM_ERROR: Groq request failed for model openai/gpt-oss-120b',
      /isn’t available right now/,
    ],
  ]) {
    const db = makeDb();
    const createRes = makeRes();
    await handler(
      {
        method: 'POST',
        body: { course_name: 'CS 10', course_website_url: 'https://cs.example.edu/' },
      },
      createRes,
      { verifyUserAuth: authorized, getDb: () => db, importCourseWebsite: emptyWebsiteImport },
    );
    const syncRes = makeRes();
    await handler(
      {
        method: 'PUT',
        body: { action: 'sync_course_website', course_id: createRes.body.course.course_id },
      },
      syncRes,
      {
        verifyUserAuth: authorized,
        getDb: () => db,
        importCourseWebsite: async () => { throw new Error(marker); },
      },
    );
    assert.equal(syncRes.statusCode, 503);
    assert.match(syncRes.body.error, expectedMessage);
    assertNoInternals(syncRes.body.error);
  }
});

test('website imports that exceed the time budget fail with a specific message', async () => {
  const db = makeDb();
  const createRes = makeRes();
  await handler(
    {
      method: 'POST',
      body: { course_name: 'CS 10', course_website_url: 'https://cs.example.edu/' },
    },
    createRes,
    { verifyUserAuth: authorized, getDb: () => db, importCourseWebsite: emptyWebsiteImport },
  );
  const syncRes = makeRes();
  await handler(
    {
      method: 'PUT',
      body: { action: 'sync_course_website', course_id: createRes.body.course.course_id },
    },
    syncRes,
    {
      verifyUserAuth: authorized,
      getDb: () => db,
      importCourseWebsite: async () => {
        throw new Error('WEBSITE_IMPORT_TIME_BUDGET_ERROR: The import ran out of time.');
      },
    },
  );
  assert.equal(syncRes.statusCode, 504);
  assert.match(syncRes.body.error, /took too long to sync/);
  assertNoInternals(syncRes.body.error);
  assert.match(syncRes.body.error, /No assignments were imported/);
});

test('daily AI quota errors tell instructors when to retry without naming the provider', async () => {
  const db = makeDb();
  const createRes = makeRes();
  await handler(
    {
      method: 'POST',
      body: { course_name: 'CS 10', course_website_url: 'https://cs.example.edu/' },
    },
    createRes,
    { verifyUserAuth: authorized, getDb: () => db, importCourseWebsite: emptyWebsiteImport },
  );
  const syncRes = makeRes();
  await handler(
    {
      method: 'PUT',
      body: { action: 'sync_course_website', course_id: createRes.body.course.course_id },
    },
    syncRes,
    {
      verifyUserAuth: authorized,
      getDb: () => db,
      importCourseWebsite: async () => {
        throw new Error(
          'WEBSITE_IMPORT_DAILY_QUOTA_ERROR: retry after 1278 seconds',
        );
      },
    },
  );
  assert.equal(syncRes.statusCode, 429);
  assert.match(syncRes.body.error, /busy right now.*about 22 minutes/);
  assertNoInternals(syncRes.body.error);
});

test('Gradescope sync rejects courses without a Gradescope ID', async () => {
  const db = makeDb();
  const createRes = makeRes();
  await handler(
    { method: 'POST', body: { course_name: 'CS 10' } },
    createRes,
    { verifyUserAuth: authorized, getDb: () => db },
  );
  const importCourse = async () => {
    assert.fail('Gradescope should not be called for a course without a Gradescope ID');
  };
  const syncRes = makeRes();
  await handler(
    { method: 'PUT', body: { action: 'sync_gradescope', course_id: createRes.body.course.course_id } },
    syncRes,
    { verifyUserAuth: authorized, getDb: () => db, importCourse },
  );
  assert.equal(syncRes.statusCode, 400);
  assert.match(syncRes.body.error, /Gradescope Course ID/);
});

test('instructor finalizes only approved imported assignments', async () => {
  const db = makeDb();
  const createRes = makeRes();
  await handler(
    {
      method: 'POST',
      body: {
        course_name: 'CS 10',
        gradescope_url: '12345',
        course_website_url: 'https://cs.example.edu/course',
      },
    },
    createRes,
    {
      verifyUserAuth: authorized,
      getDb: () => db, importCourseWebsite: emptyWebsiteImport,
      importCourse: async id => ({
        course_id: id,
        assignments: [
          { id: '67890', title: 'Homework 1', due: '2026-10-30T23:59:00Z' },
          { id: '67891', title: 'Homework 2', due: '2026-11-06T23:59:00Z' },
        ],
      }),
    },
  );

  const courseId = createRes.body.course.course_id;
  const res = makeRes();
  await handler(
    {
      method: 'PUT',
      body: { action: 'finalize', course_id: courseId, approved_assignment_ids: ['67891'] },
    },
    res,
    { verifyUserAuth: authorized, getDb: () => db },
  );
  assert.equal(res.statusCode, 200);
  assert.equal(res.body.course.status, 'finalized');
  assert.equal(res.body.course.assignment_count, 1);
  assert.equal(res.body.course.course_website_url, 'https://cs.example.edu/course');
  assert.equal(db._docs.has(`instructor_course_assignments/uid-1__${courseId}__67891`), true);
  assert.equal(db._docs.has(`instructor_course_assignments/uid-1__${courseId}__67890`), false);
  assert.equal(db._docs.has(`instructor_course_assignment_reviews/uid-1__${courseId}__67890`), false);
  assert.equal(db._docs.has(`instructor_course_assignment_reviews/uid-1__${courseId}__67891`), false);

  const listRes = makeRes();
  await handler(
    { method: 'GET' },
    listRes,
    { verifyUserAuth: authorized, getDb: () => db },
  );
  assert.equal(listRes.statusCode, 200);
  assert.deepEqual(listRes.body.courses[0].assignments.map(assignment => assignment.assignment_id), ['67891']);
  assert.deepEqual(listRes.body.courses[0].pending_assignments, []);
});

test('assignments with the same due date sort by assignment name', async () => {
  const db = makeDb();
  const createRes = makeRes();
  await handler(
    { method: 'POST', body: { course_name: 'CS 10', gradescope_url: '12345' } },
    createRes,
    {
      verifyUserAuth: authorized,
      getDb: () => db,
      importCourse: async id => ({
        course_id: id,
        assignments: [
          { id: 'hw10', title: 'Homework 10', due: '2026-11-06T23:59:00Z' },
          { id: 'hw8', title: 'Homework 8', due: '2026-11-06T23:59:00Z' },
          { id: 'hw7', title: 'Homework 7', due: '2026-11-06T23:59:00Z' },
        ],
      }),
    },
  );

  const courseId = createRes.body.course.course_id;
  const finalizeRes = makeRes();
  await handler(
    {
      method: 'PUT',
      body: { action: 'finalize', course_id: courseId, approved_assignment_ids: ['hw10', 'hw8', 'hw7'] },
    },
    finalizeRes,
    { verifyUserAuth: authorized, getDb: () => db },
  );
  assert.equal(finalizeRes.statusCode, 200);

  const listRes = makeRes();
  await handler({ method: 'GET' }, listRes, { verifyUserAuth: authorized, getDb: () => db });
  assert.deepEqual(
    listRes.body.courses[0].assignments.map(assignment => assignment.assignment_name),
    ['Homework 7', 'Homework 8', 'Homework 10'],
  );
});

test('instructor can finalize a course while rejecting all imported assignments', async () => {
  const db = makeDb();
  const createRes = makeRes();
  await handler(
    { method: 'POST', body: { course_name: 'CS 10', gradescope_url: '12345' } },
    createRes,
    {
      verifyUserAuth: authorized,
      getDb: () => db,
      importCourse: async id => ({
        course_id: id,
        assignments: [{ id: '67890', title: 'Not an assignment', due: '2026-10-01' }],
      }),
    },
  );

  const courseId = createRes.body.course.course_id;
  const res = makeRes();
  await handler(
    { method: 'PUT', body: { action: 'finalize', course_id: courseId, approved_assignment_ids: [] } },
    res,
    { verifyUserAuth: authorized, getDb: () => db },
  );
  assert.equal(res.statusCode, 200);
  assert.equal(res.body.course.status, 'finalized');
  assert.equal(res.body.course.assignment_count, 0);
  assert.equal(db._docs.has(`instructor_course_assignments/uid-1__${courseId}__67890`), false);
});

test('instructor cannot finalize a course that is not owned or pending review', async () => {
  const db = makeDb();
  const res = makeRes();
  await handler(
    {
      method: 'PUT',
      body: { action: 'finalize', course_id: 'not-owned-course', approved_assignment_ids: [] },
    },
    res,
    { verifyUserAuth: authorized, getDb: () => db },
  );
  assert.equal(res.statusCode, 404);
  assert.equal(res.body.error, 'Course review not found.');
});

test('instructor cannot edit a course owned by another user', async () => {
  const db = makeDb();
  const res = makeRes();
  await handler(
    {
      method: 'PUT',
      body: { course_id: 'not-owned-course', course_name: 'Changed' },
    },
    res,
    { verifyUserAuth: authorized, getDb: () => db },
  );
  assert.equal(res.statusCode, 404);
  assert.equal(res.body.error, 'Course not found.');
});

test('instructor can archive and restore their course', async () => {
  const db = makeDb();
  const createRes = makeRes();
  await handler(
    { method: 'POST', body: { course_name: 'CS 10', term: 'Fall 2026' } },
    createRes,
    { verifyUserAuth: authorized, getDb: () => db },
  );
  const courseId = createRes.body.course.course_id;

  const archiveRes = makeRes();
  await handler(
    { method: 'PUT', body: { action: 'archive', course_id: courseId } },
    archiveRes,
    { verifyUserAuth: authorized, getDb: () => db },
  );
  assert.equal(archiveRes.statusCode, 200);
  assert.equal(archiveRes.body.course.archived, true);

  const listRes = makeRes();
  await handler(
    { method: 'GET' },
    listRes,
    { verifyUserAuth: authorized, getDb: () => db },
  );
  assert.equal(listRes.body.courses[0].archived, true);
  assert.equal(listRes.body.courses[0].term, 'Fall 2026');

  const restoreRes = makeRes();
  await handler(
    { method: 'PUT', body: { action: 'unarchive', course_id: courseId } },
    restoreRes,
    { verifyUserAuth: authorized, getDb: () => db },
  );
  assert.equal(restoreRes.statusCode, 200);
  assert.equal(restoreRes.body.course.archived, false);
});

test('instructor cannot archive a course owned by another user', async () => {
  const res = makeRes();
  await handler(
    { method: 'PUT', body: { action: 'archive', course_id: 'not-owned-course' } },
    res,
    { verifyUserAuth: authorized, getDb: () => makeDb() },
  );
  assert.equal(res.statusCode, 404);
  assert.equal(res.body.error, 'Course not found.');
});

test('instructor can delete their course and its assignments and pending reviews', async () => {
  const db = makeDb();
  const createRes = makeRes();
  await handler(
    { method: 'POST', body: { course_name: 'CS 10', gradescope_url: '12345' } },
    createRes,
    {
      verifyUserAuth: authorized,
      getDb: () => db,
      importCourse: async id => ({
        course_id: id,
        assignments: [{ id: '67890', title: 'Homework 1', due: '2026-10-01' }],
      }),
    },
  );
  const courseId = createRes.body.course.course_id;
  db._docs.set(`instructor_course_assignments/uid-1__${courseId}__67891`, {
    owner_uid: 'uid-1',
    course_id: courseId,
    assignment_id: '67891',
  });

  const res = makeRes();
  await handler(
    { method: 'DELETE', body: { course_id: courseId } },
    res,
    { verifyUserAuth: authorized, getDb: () => db },
  );

  assert.equal(res.statusCode, 200);
  assert.equal(res.body.course.course_name, 'CS 10');
  assert.equal(db._docs.has(`instructor_courses/uid-1__${courseId}`), false);
  assert.equal(db._docs.has(`instructor_course_assignment_reviews/uid-1__${courseId}__67890`), false);
  assert.equal(db._docs.has(`instructor_course_assignments/uid-1__${courseId}__67891`), false);
});

test('instructor cannot delete a course owned by another user', async () => {
  const db = makeDb();
  const res = makeRes();
  await handler(
    { method: 'DELETE', body: { course_id: 'not-owned-course' } },
    res,
    { verifyUserAuth: authorized, getDb: () => db },
  );

  assert.equal(res.statusCode, 404);
  assert.equal(res.body.error, 'Course not found.');
});

test('course import rejects invalid IDs without contacting Gradescope', async () => {
  const db = makeDb();
  let importCalled = false;
  const res = makeRes();
  await handler(
    { method: 'POST', body: { course_name: 'CS 10', gradescope_url: 'not-a-course' } },
    res,
    {
      verifyUserAuth: authorized,
      getDb: () => db,
      importCourse: async () => { importCalled = true; },
    },
  );
  assert.equal(res.statusCode, 400);
  assert.equal(importCalled, false);
});

test('a course can sync from both configured assignment sources', async () => {
  const db = makeDb();
  const createRes = makeRes();
  await handler(
    {
      method: 'POST',
      body: {
        course_name: 'CS 10',
        gradescope_url: '12345',
        course_website_url: 'https://cs.example.edu/course',
      },
    },
    createRes,
    {
      verifyUserAuth: authorized,
      getDb: () => db, importCourseWebsite: emptyWebsiteImport,
      importCourse: async id => ({
        course_id: id,
        course_name: 'CS 10',
        course_url: '',
        assignments: [],
      }),
    },
  );
  assert.equal(createRes.statusCode, 200);
  const courseId = createRes.body.course.course_id;
  assert.equal(createRes.body.course.gradescope_course_id, '12345');
  assert.equal(createRes.body.course.course_website_url, 'https://cs.example.edu/course');

  let gradescopeImported = false;
  let websiteImported = false;
  const syncRes = makeRes();
  await handler(
    { method: 'PUT', body: { action: 'sync_all_sources', course_id: courseId } },
    syncRes,
    {
      verifyUserAuth: authorized,
      getDb: () => db,
      importCourse: async id => {
        gradescopeImported = true;
        return {
          course_id: id,
          course_url: 'https://www.gradescope.com/courses/12345',
          assignments: [{ id: 'gs-homework', title: 'Gradescope Homework', due: '2026-10-01' }],
        };
      },
      importCourseWebsite: async url => {
        websiteImported = true;
        return {
          course_url: url,
          pages_crawled: 1,
          candidates_reviewed: 1,
          assignments: [{
            id: '0123456789abcdef0123456789abcdef',
            title: 'Website Homework',
            due: null,
            html_url: `${url}hw1`,
            source: 'website',
            resources: [],
          }],
        };
      },
    },
  );
  assert.equal(syncRes.statusCode, 200);
  assert.equal(gradescopeImported, true);
  assert.equal(websiteImported, true);
  assert.equal(syncRes.body.course.new_assignment_count, 2);
  assert.equal(syncRes.body.course.course_website_pages_crawled, 1);
  assert.deepEqual(
    syncRes.body.course.new_assignments.map(assignment => assignment.source).sort(),
    ['gradescope', 'website'],
  );
  assert.equal(syncRes.body.course.gradescope_course_id, '12345');
  assert.equal(syncRes.body.course.course_website_url, 'https://cs.example.edu/course');
});

test('a re-sync records the course website as a second source of items the course already has', async () => {
  const db = makeDb();
  const gradescope = async id => ({
    course_id: id,
    course_name: 'CS 10',
    course_url: 'https://www.gradescope.com/courses/12345',
    assignments: [
      { id: 'gs-hw1', title: 'Homework 1', due: '2026-10-01' },
      { id: 'gs-hw2', title: 'Homework 2', due: '2026-10-08' },
    ],
  });
  const createRes = makeRes();
  await handler(
    { method: 'POST', body: { course_name: 'CS 10', gradescope_url: '12345', course_website_url: 'https://cs.example.edu/course' } },
    createRes,
    { verifyUserAuth: authorized, getDb: () => db, importCourseWebsite: emptyWebsiteImport, importCourse: gradescope },
  );
  assert.equal(createRes.statusCode, 200);
  const courseId = createRes.body.course.course_id;

  const syncRes = makeRes();
  await handler(
    { method: 'PUT', body: { action: 'sync_all_sources', course_id: courseId } },
    syncRes,
    {
      verifyUserAuth: authorized,
      getDb: () => db,
      importCourse: gradescope,
      importCourseWebsite: async url => ({
        course_url: url,
        pages_crawled: 1,
        candidates_reviewed: 2,
        assignments: [
          { id: '0123456789abcdef0123456789abcdef', title: 'Homework 1', due: '2026-10-01', html_url: `${url}hw1`, source: 'website', resources: [] },
          // A different date is not recorded silently.
          { id: 'fedcba9876543210fedcba9876543210', title: 'Homework 2', due: '2026-10-09', html_url: `${url}hw2`, source: 'website', resources: [] },
        ],
      }),
    },
  );
  assert.equal(syncRes.statusCode, 200);
  const stored = id => [...db._docs.values()].find(data => data.assignment_id === id && data.course_id === courseId);
  assert.deepEqual(stored('gs-hw1').merged_versions.map(version => version.source), ['gradescope', 'website']);
  assert.ok(stored('gs-hw1').source_ids.includes('0123456789abcdef0123456789abcdef'));
  // Still in review, so the sync shows both dates and leaves the choice to the instructor.
  assert.deepEqual(stored('gs-hw2').merged_versions.map(version => [version.source, version.due]),
    [['gradescope', '2026-10-08'], ['website', '2026-10-09']]);
  assert.equal(stored('gs-hw2').due, null);
  assert.ok(stored('gs-hw2').review_reasons.length);

  // Syncing again does not list the website twice.
  const againRes = makeRes();
  await handler(
    { method: 'PUT', body: { action: 'sync_all_sources', course_id: courseId } },
    againRes,
    {
      verifyUserAuth: authorized,
      getDb: () => db,
      importCourse: gradescope,
      importCourseWebsite: async url => ({
        course_url: url,
        pages_crawled: 1,
        candidates_reviewed: 1,
        assignments: [
          { id: '0123456789abcdef0123456789abcdef', title: 'Homework 1', due: '2026-10-01', html_url: `${url}hw1`, source: 'website', resources: [] },
        ],
      }),
    },
  );
  assert.equal(againRes.statusCode, 200);
  assert.equal(stored('gs-hw1').merged_versions.length, 2);
});

test('a re-sync replaces stale review items but keeps the ones the instructor edited', async () => {
  const db = makeDb();
  const createRes = makeRes();
  await handler(
    { method: 'POST', body: { course_name: 'CS 61A', term: 'Fall 2026', course_website_url: 'https://cs.example.edu/' } },
    createRes,
    { verifyUserAuth: authorized, getDb: () => db, importCourseWebsite: emptyWebsiteImport },
  );
  const courseId = createRes.body.course.course_id;
  const syncWith = async assignments => {
    const res = makeRes();
    await handler(
      { method: 'PUT', body: { action: 'sync_course_website', course_id: courseId } },
      res,
      {
        verifyUserAuth: authorized,
        getDb: () => db,
        importCourseWebsite: async url => ({ course_url: url, pages_crawled: 1, candidates_reviewed: 1, assignments }),
      },
    );
    assert.equal(res.statusCode, 200);
    return res;
  };
  const item = (id, title, due) => ({ id, title, due, html_url: 'https://cs.example.edu/', source: 'website', resources: [] });
  const inReview = () => [...db._docs.values()]
    .filter(data => data.course_id === courseId && data.assignment_name)
    .map(data => [data.assignment_name, data.due]).sort();

  await syncWith([item('a'.repeat(32), 'Quiz 1', '2026-09-04'), item('b'.repeat(32), 'Lab 2', '2026-09-09')]);
  const lab = [...db._docs.values()].find(data => data.assignment_id === 'b'.repeat(32));
  const editRes = makeRes();
  await handler(
    { method: 'PUT', body: { action: 'update_assignment', course_id: courseId, assignment_id: lab.assignment_id, assignment_name: 'Lab 2', due: '2026-09-10' } },
    editRes,
    { verifyUserAuth: authorized, getDb: () => db },
  );

  // The importer now reads Quiz 1 as undated and Lab 2 differently.
  const res = await syncWith([item('c'.repeat(32), 'Quiz 1', null), item('d'.repeat(32), 'Lab 2', '2026-09-09')]);

  assert.deepEqual(inReview(), [['Lab 2', '2026-09-09'], ['Lab 2', '2026-09-10'], ['Quiz 1', null]]);
  // Both changed from what was waiting for review: Quiz 1's date and Lab 2's new reading.
  assert.equal(res.body.course.new_assignment_count, 2);
});

test('Gradescope course ID can be entered without its URL', async () => {
  const db = makeDb();
  let importedId;
  const res = makeRes();
  await handler(
    { method: 'POST', body: { course_name: 'CS 10', gradescope_url: '12345' } },
    res,
    {
      verifyUserAuth: authorized,
      getDb: () => db,
      importCourse: async id => {
        importedId = id;
        return { course_id: id, course_name: 'CS 10', course_url: '', assignments: [] };
      },
    },
  );
  assert.equal(res.statusCode, 200);
  assert.equal(importedId, '12345');
  assert.equal(res.body.course.gradescope_url, 'https://www.gradescope.com/courses/12345');
});

test('Gradescope entry codes are rejected because only numeric course IDs are supported', async () => {
  const db = makeDb();
  let importCalled = false;
  const res = makeRes();
  await handler(
    { method: 'POST', body: { course_name: 'CS 10', gradescope_url: '7KN4P5' } },
    res,
    {
      verifyUserAuth: authorized,
      getDb: () => db,
      importCourse: async () => { importCalled = true; },
    },
  );
  assert.equal(res.statusCode, 400);
  assert.match(res.body.error, /numeric Gradescope Course ID/i);
  assert.equal(importCalled, false);
});

test('missing Gradescope server credentials show a generic unavailable message', async () => {
  const res = makeRes();
  await handler(
    { method: 'POST', body: { course_name: 'CS 10', gradescope_url: '12345' } },
    res,
    {
      verifyUserAuth: authorized,
      getDb: () => makeDb(),
      importCourse: async () => {
        throw new Error('GRADESCOPE_CONFIG_ERROR: Configure Gradescope credentials');
      },
    },
  );
  assert.equal(res.statusCode, 503);
  assert.match(res.body.error, /couldn’t connect to Gradescope right now/);
  assertNoInternals(res.body.error);
});

test('Gradescope login failures show a generic unavailable message', async () => {
  const res = makeRes();
  await handler(
    { method: 'POST', body: { course_name: 'CS 10', gradescope_url: '12345' } },
    res,
    {
      verifyUserAuth: authorized,
      getDb: () => makeDb(),
      importCourse: async () => {
        throw new Error('GRADESCOPE_AUTH_ERROR: Gradescope rejected the shared account login (HTTP 401).');
      },
    },
  );
  assert.equal(res.statusCode, 503);
  assert.match(res.body.error, /couldn’t connect to Gradescope right now/);
  assertNoInternals(res.body.error);
});

test('legacy bCourses course IDs are ignored when creating a course', async () => {
  const db = makeDb();
  let importCalled = false;
  const res = makeRes();
  await handler(
    {
      method: 'POST',
      body: {
        course_name: 'Data Science 1',
        bcourses_url: '7KN4P5',
      },
    },
    res,
    {
      verifyUserAuth: authorized,
      getDb: () => db,
      importCourse: async () => { importCalled = true; },
    },
  );
  assert.equal(res.statusCode, 200);
  assert.equal(importCalled, false);
  assert.equal(res.body.course.course_name, 'Data Science 1');
  assert.equal(res.body.course.assignment_count, 0);
  assert.equal('bcourses_course_id' in res.body.course, false);
  assert.equal('bcourses_url' in res.body.course, false);
  assert.ok(db._docs.has(`instructor_courses/uid-1__${res.body.course.course_id}`));
});

test('course creation rejects unsafe or unrelated platform URLs', async () => {
  const db = makeDb();
  const res = makeRes();
  await handler(
    {
      method: 'POST',
      body: {
        course_name: 'CS 10',
        gradescope_url: 'https://www.gradescope.com.evil.example/courses/12345',
      },
    },
    res,
    { verifyUserAuth: authorized, getDb: () => db },
  );
  assert.equal(res.statusCode, 400);
});

test('course creation rejects full URLs because only numeric course IDs are accepted', async () => {
  const res = makeRes();
  await handler(
    {
      method: 'POST',
      body: {
        course_name: 'CS 10',
        gradescope_url: 'https://www.gradescope.com/courses/12345',
      },
    },
    res,
    { verifyUserAuth: authorized, getDb: () => makeDb() },
  );
  assert.equal(res.statusCode, 400);
  assert.match(res.body.error, /numeric Gradescope Course ID/i);
});

test('instructor assignment removal falls back to query if document ID is non-standard', async () => {
  const db = makeDb();
  const courseId = 'cs10-custom';
  db._docs.set(`instructor_courses/uid-1__${courseId}`, {
    owner_uid: 'uid-1',
    course_id: courseId,
    course_name: 'CS 10',
    status: 'finalized',
    assignment_count: 1,
  });
  // Simulate a doc with an arbitrary/legacy key not matching assignmentDocumentId format
  db._docs.set('instructor_course_assignments/legacy-key-xyz', {
    owner_uid: 'uid-1',
    course_id: courseId,
    assignment_id: 'legacy-assign-1',
    assignment_name: 'Legacy Assignment',
  });

  const res = makeRes();
  await handler(
    {
      method: 'PUT',
      body: { action: 'remove_assignment', course_id: courseId, assignment_id: 'legacy-assign-1' },
    },
    res,
    { verifyUserAuth: authorized, getDb: () => db },
  );

  assert.equal(res.statusCode, 200);
  assert.equal(res.body.success, true);
  assert.equal(db._docs.has('instructor_course_assignments/legacy-key-xyz'), false);
  assert.equal(db._docs.get(`instructor_courses/uid-1__${courseId}`).assignment_count, 0);
});

test('instructor assignment creation and editing preserves custom resource tags', async () => {
  const db = makeDb();
  const courseId = 'cs61a-tags';
  db._docs.set(`instructor_courses/uid-1__${courseId}`, {
    owner_uid: 'uid-1',
    course_id: courseId,
    course_name: 'CS 61A',
    status: 'finalized',
    assignment_count: 0,
  });

  const addRes = makeRes();
  await handler(
    {
      method: 'PUT',
      body: {
        action: 'add_assignment',
        course_id: courseId,
        assignment_name: 'Project 1 Hog',
        due: '2026-09-15',
        resources: [
          { resource_name: 'Project Spec', resource_type: 'Spec', link: 'https://cs61a.org/proj/hog/' },
          { resource_name: 'Starter Code', resource_type: 'Starter Code', link: 'https://cs61a.org/proj/hog.zip' },
        ],
      },
    },
    addRes,
    { verifyUserAuth: authorized, getDb: () => db },
  );

  assert.equal(addRes.statusCode, 200);
  assert.equal(addRes.body.success, true);
  assert.deepEqual(addRes.body.assignment.resources, [
    { resource_name: 'Project Spec', resource_type: 'Spec', link: 'https://cs61a.org/proj/hog/' },
    { resource_name: 'Starter Code', resource_type: 'Starter Code', link: 'https://cs61a.org/proj/hog.zip' },
  ]);
});

test('versions of one deadline staged for review are merged into one item when listed', async () => {
  const db = makeDb();
  db._docs.set('instructor_courses/uid-1__cs10', {
    owner_uid: 'uid-1', course_id: 'cs10', course_name: 'CS 10', term: 'Fall 2026',
    status: 'pending_review', pending_assignment_count: 4,
  });
  const staged = (id, name, due, reasons = []) => db._docs.set(
    `instructor_course_assignment_reviews/uid-1__cs10__${id}`,
    {
      owner_uid: 'uid-1', course_id: 'cs10', assignment_id: id, assignment_name: name,
      due, source: 'gradescope', html_url: '', resources: [], review_reasons: reasons,
    },
  );
  // Legacy item with "Same name as" notes.
  staged('1', 'Lab 2: Build Your Own Blocks (Code)', '2026-09-10', ['Same name as “Lab 2: Build Your Own Blocks (Conceptual)”']);
  staged('2', 'Lab 2: Build Your Own Blocks (Conceptual)', '2026-09-10', ['Same name as “Lab 2: Build Your Own Blocks (Code)”']);
  staged('3', 'Optional Lab 2: Object-Oriented Programming (Code)', '2026-09-10', ['Same name as “Lab 2: Build Your Own Blocks (Code)”']);
  staged('4', 'Homework 1', '2026-09-05', ['Due 2026-09-05, which is outside Fall 2026. Check the date.']);

  const res = makeRes();
  await handler({ method: 'GET' }, res, { verifyUserAuth: authorized, getDb: () => db });
  const course = res.body.courses[0];
  assert.equal(course.pending_assignment_count, 2);
  assert.deepEqual(
    course.pending_assignments.map(item => [item.assignment_id, item.assignment_name, item.due, item.review_reasons]),
    [['4', 'Homework 1', '2026-09-05', []], ['1', 'Lab 2', '2026-09-10', []]],
  );
  assert.equal(course.pending_assignments[1].merged_versions.length, 3);
  // Saved: the merged item replaces its versions.
  assert.equal(db._docs.has('instructor_course_assignment_reviews/uid-1__cs10__2'), false);
  assert.equal(db._docs.get('instructor_course_assignment_reviews/uid-1__cs10__1').assignment_name, 'Lab 2');

  // Publishing it keeps the versions it stands for; a checked version is also
  // added as its own deadline.
  const finalizeRes = makeRes();
  await handler(
    { method: 'PUT', body: { action: 'finalize', course_id: 'cs10', approved_assignment_ids: ['1', '4', '1#v1'] } },
    finalizeRes,
    { verifyUserAuth: authorized, getDb: () => db },
  );
  assert.equal(finalizeRes.statusCode, 200, JSON.stringify(finalizeRes.body));
  const published = db._docs.get('instructor_course_assignments/uid-1__cs10__1');
  assert.equal(published.assignment_name, 'Lab 2');
  assert.equal(published.merged_versions.length, 3);
  const version = db._docs.get('instructor_course_assignments/uid-1__cs10__1-v1');
  assert.equal(version.assignment_name, 'Lab 2: Build Your Own Blocks (Conceptual)');
  assert.equal(version.due, '2026-09-10');
});

test('versions of a merged item can be added on their own after a later sync', async () => {
  const db = makeDb();
  db._docs.set('instructor_courses/uid-1__cs10', {
    owner_uid: 'uid-1', course_id: 'cs10', course_name: 'CS 10', status: 'finalized', assignment_count: 0,
  });
  db._docs.set('instructor_course_assignment_reviews/uid-1__cs10__1', {
    owner_uid: 'uid-1', course_id: 'cs10', assignment_id: '1', assignment_name: 'Lab 2', due: '2026-09-10',
    source: 'gradescope', html_url: '', resources: [], review_reasons: [], source_ids: ['1', '2', '3'],
    merged_versions: [
      { assignment_name: 'Lab 2 (Code)', due: '2026-09-10', source: 'gradescope', html_url: '' },
      { assignment_name: 'Lab 2 (Conceptual)', due: '2026-09-11', source: 'gradescope', html_url: '' },
      { assignment_name: 'Lab 2 (Notes)', due: null, source: 'website', html_url: '' },
    ],
  });
  const review = ids => {
    const res = makeRes();
    return handler(
      { method: 'PUT', body: { action: 'review_synced_assignments', course_id: 'cs10', approved_assignment_ids: ids } },
      res,
      { verifyUserAuth: authorized, getDb: () => db },
    ).then(() => res);
  };
  // An undated version can't be added, and unknown versions are refused.
  assert.equal((await review(['1#v2'])).statusCode, 400);
  assert.equal((await review(['1#v9'])).statusCode, 400);

  const res = await review(['1#v1']);
  assert.equal(res.statusCode, 200, JSON.stringify(res.body));
  assert.equal(db._docs.get('instructor_course_assignments/uid-1__cs10__1-v1').assignment_name, 'Lab 2 (Conceptual)');
  assert.equal(db._docs.has('instructor_course_assignments/uid-1__cs10__1'), false);
});

test('a version of a merged item can be edited and deleted like an assignment', async () => {
  const db = makeDb();
  db._docs.set('instructor_courses/uid-1__cs10', {
    owner_uid: 'uid-1', course_id: 'cs10', course_name: 'CS 10', status: 'pending_review',
  });
  const key = 'instructor_course_assignment_reviews/uid-1__cs10__1';
  db._docs.set(key, {
    owner_uid: 'uid-1', course_id: 'cs10', assignment_id: '1', assignment_name: 'Lab 2', due: '2026-09-10',
    source: 'gradescope', html_url: '', resources: [], review_reasons: [],
    merged_versions: [
      { assignment_name: 'Lab 2 (Code)', due: '2026-09-10', source: 'gradescope', html_url: '' },
      { assignment_name: 'Lab 2 (Conceptual)', due: null, source: 'website', html_url: '' },
    ],
  });
  const put = async body => {
    const res = makeRes();
    await handler({ method: 'PUT', body: { course_id: 'cs10', ...body } }, res, { verifyUserAuth: authorized, getDb: () => db });
    return res;
  };

  const edited = await put({
    action: 'update_assignment', assignment_id: '1#v1', assignment_name: 'Lab 2 Conceptual', due: '2026-09-11', resources: [],
  });
  assert.equal(edited.statusCode, 200, JSON.stringify(edited.body));
  assert.deepEqual(
    db._docs.get(key).merged_versions.map(version => [version.assignment_name, version.due]),
    [['Lab 2 (Code)', '2026-09-10'], ['Lab 2 Conceptual', '2026-09-11']],
  );
  // The merged item itself is untouched.
  assert.equal(db._docs.get(key).assignment_name, 'Lab 2');

  const removed = await put({ action: 'remove_assignment', assignment_id: '1#v0' });
  assert.equal(removed.statusCode, 200, JSON.stringify(removed.body));
  assert.deepEqual(db._docs.get(key).merged_versions.map(version => version.assignment_name), ['Lab 2 Conceptual']);
  assert.equal((await put({ action: 'remove_assignment', assignment_id: '1#v5' })).statusCode, 404);
});

test('items merged under the old date rule switch to the new one, and editing clears notes', async () => {
  const db = makeDb();
  db._docs.set('instructor_courses/uid-1__cs10', {
    owner_uid: 'uid-1', course_id: 'cs10', course_name: 'CS 10', status: 'pending_review',
  });
  const key = 'instructor_course_assignment_reviews/uid-1__cs10__1';
  db._docs.set(key, {
    owner_uid: 'uid-1', course_id: 'cs10', assignment_id: '1', assignment_name: 'Lab 2', due: '2026-09-10',
    source: 'gradescope', html_url: '', resources: [],
    review_reasons: ['Versions are due on different days (2026-09-10, 2026-09-12). Check the date.'],
    merged_versions: [
      { assignment_name: 'Lab 2 (Code)', due: '2026-09-10', source: 'gradescope', html_url: '' },
      { assignment_name: 'Lab 2 (OOP)', due: '2026-09-12', source: 'gradescope', html_url: '' },
    ],
  });
  const list = async () => {
    const res = makeRes();
    await handler({ method: 'GET' }, res, { verifyUserAuth: authorized, getDb: () => db });
    return res.body.courses[0].pending_assignments[0];
  };
  const before = await list();
  assert.equal(before.due, null);
  assert.deepEqual(before.review_reasons, [
    'Versions are due on different days. Use Edit to choose the due date.',
  ]);
  assert.equal(db._docs.get(key).due, null);

  const res = makeRes();
  await handler(
    { method: 'PUT', body: { action: 'update_assignment', course_id: 'cs10', assignment_id: '1', assignment_name: 'Lab 2', due: '2026-09-12', resources: [] } },
    res,
    { verifyUserAuth: authorized, getDb: () => db },
  );
  assert.equal(res.statusCode, 200, JSON.stringify(res.body));
  const after = await list();
  assert.equal(after.due, '2026-09-12');
  assert.deepEqual(after.review_reasons, []);
});

test('items combined under the old "Combines" note list their versions when listed', async () => {
  const db = makeDb();
  db._docs.set('instructor_courses/uid-1__cs61a', {
    owner_uid: 'uid-1', course_id: 'cs61a', course_name: 'CS 61A', status: 'pending_review',
  });
  const key = 'instructor_course_assignment_reviews/uid-1__cs61a__201';
  db._docs.set(key, {
    owner_uid: 'uid-1', course_id: 'cs61a', assignment_id: '201', assignment_name: 'Optional Lab 1',
    due: '2026-09-10', source: 'gradescope', html_url: 'https://www.gradescope.com/x', resources: [], review_reasons: [],
    source_ids: ['201', '202', 'w1'],
    combined_titles: [
      'Optional Lab 1: Linear Recursion in Python (Conceptual)',
      'Optional Lab 1: Linear Recursion in Python (Code)',
    ],
  });
  const res = makeRes();
  await handler({ method: 'GET' }, res, { verifyUserAuth: authorized, getDb: () => db });
  const item = res.body.courses[0].pending_assignments[0];
  assert.deepEqual(item.merged_versions.map(version => [version.assignment_name, version.due]), [
    ['Optional Lab 1: Linear Recursion in Python (Conceptual)', '2026-09-10'],
    ['Optional Lab 1: Linear Recursion in Python (Code)', '2026-09-10'],
  ]);
  assert.equal(db._docs.get(key).merged_versions.length, 2);
});
