import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { JSDOM } from 'jsdom';

// Runs the real public/index.html in a simulated browser (jsdom) with a fake
// signed-in student and fake /api responses, then clicks through the
// "Advanced options" grid and both Save buttons. Covers the dashboard side of
// extra reminder days, which the API tests can't see.

const PUBLIC = (name) => fileURLToPath(new URL(`../../public/${name}`, import.meta.url));

// Same header/footer injection src/server.js does; the page needs elements
// from both (e.g. #unsubscribe-link) or its script stops early.
const PAGE_HTML = readFileSync(PUBLIC('index.html'), 'utf8')
  .replace('<!-- HEADER -->', readFileSync(PUBLIC('_header.html'), 'utf8'))
  .replace('<!-- FOOTER -->', readFileSync(PUBLIC('_footer.html'), 'utf8'));

const CS61A = {
  course_code: 'CS61A',
  display_name: 'CS 61A',
  categories: [
    { id: 'lab', label: 'Labs' }, { id: 'homework', label: 'Homework' },
    { id: 'midterm', label: 'Midterms' }, { id: 'quiz', label: 'Quizzes' },
    { id: 'project', label: 'Projects' },
  ],
  features: {},
};

/** What GET /api/reminders/get returns for the default test student. */
function studentData(overrides = {}) {
  return {
    preferred_first_name: 'Sam',
    email: 'student@berkeley.edu',
    email_pref: true,
    phone_pref: false,
    discord_pref: false,
    days_before_deadline: 3,
    on_roster: true,
    course_code: 'CS61A',
    course: CS61A,
    category_prefs: { lab: true, homework: false, midterm: true, quiz: true, project: true },
    extra_reminder_days: { other: [], lab: [], homework: [], midterm: [], quiz: [], project: [1] },
    canvas_connected: false,
    ...overrides,
  };
}

const fakeResponse = (status, body) => ({
  ok: status >= 200 && status < 300,
  status,
  json: async () => body,
});

/**
 * Load the dashboard. `getStatus` lets a test simulate the settings load failing.
 * `holdSaves` keeps save requests pending until `releaseSaves()` is called.
 */
async function loadDashboard({ data = studentData(), getStatus = 200, holdSaves = false } = {}) {
  const saves = [];
  const pending = [];
  const dom = new JSDOM(PAGE_HTML, {
    url: 'http://localhost/index.html',
    runScripts: 'dangerously',
    pretendToBeVisual: true,
    beforeParse(window) {
      // Skip fetching /api/config; external scripts (Firebase SDK, auth.js) aren't loaded.
      window.FIREBASE_API_KEY = 'test';
      window.FIREBASE_AUTH_DOMAIN = 'test';
      window.confirm = () => true;
      window.HTMLElement.prototype.scrollIntoView = () => {};

      const user = { email: 'student@berkeley.edu', getIdToken: async () => 'token' };
      window.auth = {
        user,
        _auth: {},
        getToken: async () => 'token',
        onAuthStateChange(cb) {
          cb(null, null, true); // like the real auth.js: "loading" first
          setTimeout(() => cb(user, { user }, false), 0);
          return () => {};
        },
        signOut: async () => {},
      };

      window.fetch = async (url, opts = {}) => {
        const path = new URL(url, 'http://localhost').pathname;
        if (path === '/api/reminders/get') {
          return getStatus === 200
            ? fakeResponse(200, { success: true, data: structuredClone(data) })
            : fakeResponse(getStatus, { error: 'boom' });
        }
        if (path === '/api/reminders/settings') {
          saves.push(JSON.parse(opts.body));
          if (holdSaves) {
            await new Promise((resolve) => pending.push(resolve));
          }
          return fakeResponse(200, { success: true, waitlisted: false });
        }
        if (path === '/api/study/status') return fakeResponse(200, { status: 'autoremind' });
        return fakeResponse(200, { success: true, data: [] });
      };
    },
  });

  const { window } = dom;
  const doc = window.document;
  await waitFor(() => doc.getElementById('auth-guard') === null, 'dashboard to finish loading');

  const $ = (sel) => doc.querySelector(sel);
  const cell = (type, day) => $(`#extra-grid input[data-extra-type="${type}"][data-day="${day}"]`);
  const row = (type) => $(`#extra-grid tr[data-extra-type="${type}"]`);
  const rowTypes = () => [...doc.querySelectorAll('#extra-grid tbody tr')].map((tr) => tr.dataset.extraType);
  const setSlider = (v) => {
    const rng = $('#days-range');
    rng.value = String(v);
    rng.dispatchEvent(new window.Event('input', { bubbles: true }));
  };
  const flush = () => new Promise((r) => setTimeout(r, 20));
  const releaseSaves = () => pending.splice(0).forEach((resolve) => resolve());
  const messageShown = () => $('#message-modal')?.style.display === 'flex'
    || [...doc.querySelectorAll('.modal-overlay')].some((m) => m.style.display === 'flex'
      && m.id !== 'success-modal');

  return { window, doc, $, cell, row, rowTypes, setSlider, flush, saves, releaseSaves, messageShown,
    close: () => window.close() };
}

async function waitFor(cond, what, timeoutMs = 3000) {
  const start = Date.now();
  while (!cond()) {
    if (Date.now() - start > timeoutMs) throw new Error(`timed out waiting for ${what}`);
    await new Promise((r) => setTimeout(r, 10));
  }
}

// --- grid rendering ---------------------------------------------------------

test('grid shows one row per course type plus Other / bCourses', async (t) => {
  const d = await loadDashboard();
  t.after(d.close);
  assert.deepEqual(d.rowTypes(), ['lab', 'homework', 'midterm', 'quiz', 'project', 'other']);
  assert.equal(d.doc.querySelectorAll('#extra-grid thead th[data-day]').length, 6);
});

const isLocked = (input) => input.closest('td').classList.contains('is-locked');

test('slider day is ticked and highlighted in every row', async (t) => {
  const d = await loadDashboard();
  t.after(d.close);
  for (const type of d.rowTypes()) {
    assert.equal(d.cell(type, 3).checked, true, `${type} day 3 ticked`);
    assert.ok(isLocked(d.cell(type, 3)), `${type} day 3 highlighted`);
  }
  assert.equal(d.cell('lab', 3).disabled, false, 'slider-day cell can be clicked');
  assert.equal(d.cell('homework', 3).disabled, true, 'but not in a row whose type is off');
});

// --- unticking the main (slider) reminder per type ---------------------------

test('unticking a highlighted cell turns off only that row', async (t) => {
  const d = await loadDashboard();
  t.after(d.close);
  d.cell('project', 3).click();
  assert.equal(d.cell('project', 3).checked, false);
  assert.equal(d.cell('lab', 3).checked, true, 'other rows keep their main reminder');
  d.$('#main-cta-btn').click();
  await waitFor(() => d.saves.length === 1, 'save request');
  assert.deepEqual(d.saves[0].main_reminder_off, ['project']);
  assert.equal(d.saves[0].days_before, 3, 'slider value unchanged');
  assert.ok(!d.saves[0].extra_reminder_days.project.includes(3), 'not stored as an extra');
});

test('ticking it again turns the main reminder back on', async (t) => {
  const d = await loadDashboard();
  t.after(d.close);
  d.cell('project', 3).click();
  d.cell('project', 3).click();
  assert.equal(d.cell('project', 3).checked, true);
  d.$('#main-cta-btn').click();
  await waitFor(() => d.saves.length === 1, 'save request');
  assert.deepEqual(d.saves[0].main_reminder_off, []);
});

test('saved main_reminder_off loads unticked, and follows the slider', async (t) => {
  const d = await loadDashboard({ data: studentData({ main_reminder_off: ['lab'] }) });
  t.after(d.close);
  assert.equal(d.cell('lab', 3).checked, false);
  assert.equal(d.cell('project', 3).checked, true);
  d.setSlider(5);
  assert.equal(d.cell('lab', 5).checked, false, 'still off in the new highlighted column');
  assert.equal(d.cell('lab', 3).checked, false, 'old column is a plain unticked extra');
  assert.equal(d.cell('project', 5).checked, true);
});

test('saved extras load ticked and editable', async (t) => {
  const d = await loadDashboard();
  t.after(d.close);
  assert.equal(d.cell('project', 1).checked, true);
  assert.equal(d.cell('project', 1).disabled, false);
  assert.equal(d.cell('lab', 1).checked, false);
});

test('type switched off under "Send reminders for" has a greyed, disabled row', async (t) => {
  const d = await loadDashboard();
  t.after(d.close);
  assert.ok(d.row('homework').classList.contains('is-off'));
  assert.equal(d.cell('homework', 1).disabled, true);
  assert.ok(!d.row('other').classList.contains('is-off'), 'Other is never switched off');
});

test('turning a type on/off under "Send reminders for" updates its row', async (t) => {
  const d = await loadDashboard();
  t.after(d.close);
  d.$('#cat-homework').click();
  assert.ok(!d.row('homework').classList.contains('is-off'));
  assert.equal(d.cell('homework', 1).disabled, false);
  d.$('#cat-lab').click();
  assert.ok(d.row('lab').classList.contains('is-off'));
  assert.equal(d.cell('lab', 1).disabled, true);
});

test('student not on a roster only sees the Other / bCourses row', async (t) => {
  const d = await loadDashboard({ data: studentData({
    on_roster: false, course: null, course_code: null, extra_reminder_days: { other: [2] },
  }) });
  t.after(d.close);
  assert.deepEqual(d.rowTypes(), ['other']);
  assert.equal(d.cell('other', 2).checked, true);
});

// --- slider interaction -----------------------------------------------------

test('moving the slider moves the locked column; ticked extras survive', async (t) => {
  const d = await loadDashboard();
  t.after(d.close);
  d.setSlider(1);
  assert.ok(isLocked(d.cell('project', 1)), 'project day 1 now the highlighted main reminder');
  assert.equal(d.cell('lab', 3).checked, false, 'old slider day no longer ticked');
  assert.equal(d.cell('lab', 3).disabled, false);
  d.setSlider(3);
  assert.equal(d.cell('project', 1).checked, true, 'extra still ticked after slider moves away');
  assert.ok(!isLocked(d.cell('project', 1)));
});

test('typing in the number box also moves the locked column', async (t) => {
  const d = await loadDashboard();
  t.after(d.close);
  const num = d.$('#days');
  num.value = '5';
  num.dispatchEvent(new d.window.Event('input', { bubbles: true }));
  assert.ok(isLocked(d.cell('lab', 5)));
  assert.ok(!isLocked(d.cell('lab', 3)));
});

// --- saving -----------------------------------------------------------------

test('Save Settings sends ticked extras, without the locked slider day', async (t) => {
  const d = await loadDashboard();
  t.after(d.close);
  d.cell('quiz', 0).click();
  d.cell('lab', 5).click();
  d.$('#main-cta-btn').click();
  await waitFor(() => d.saves.length === 1, 'save request');
  const sent = d.saves[0];
  assert.equal(sent.days_before, 3);
  assert.deepEqual(sent.extra_reminder_days.quiz, [0]);
  assert.deepEqual(sent.extra_reminder_days.lab, [5]);
  assert.deepEqual(sent.extra_reminder_days.project, [1]);
  for (const days of Object.values(sent.extra_reminder_days)) {
    assert.ok(!days.includes(3), 'slider day is never stored as an extra');
  }
});

test('unticking a saved extra sends it as cleared', async (t) => {
  const d = await loadDashboard();
  t.after(d.close);
  d.cell('project', 1).click();
  d.$('#main-cta-btn').click();
  await waitFor(() => d.saves.length === 1, 'save request');
  assert.deepEqual(d.saves[0].extra_reminder_days.project, []);
});

test('in-grid Save sends exactly what Save Settings sends', async (t) => {
  const d = await loadDashboard();
  t.after(d.close);
  d.cell('midterm', 2).click();
  d.$('#extra-save-btn').click();
  await waitFor(() => d.saves.length === 1, 'in-grid save');
  await d.flush();
  d.$('#main-cta-btn').click();
  await waitFor(() => d.saves.length === 2, 'main save');
  assert.deepEqual(d.saves[0], d.saves[1]);
  assert.deepEqual(d.saves[0].extra_reminder_days.midterm, [2]);
});

test('in-grid Save lives inside Advanced options, so it folds away with it', async (t) => {
  const d = await loadDashboard();
  t.after(d.close);
  assert.equal(d.$('#extra-save-btn').closest('details'), d.$('#extra-reminders'));
  assert.equal(d.$('#extra-reminders').open, false, 'Advanced options starts folded');
  assert.ok(d.$('#main-cta-btn'), 'main Save Settings button still exists');
});

test('while saving, both buttons are disabled and a second click does not double-save', async (t) => {
  const d = await loadDashboard({ holdSaves: true });
  t.after(d.close);
  const main = d.$('#main-cta-btn');
  const inGrid = d.$('#extra-save-btn');
  inGrid.click();
  await waitFor(() => d.saves.length === 1, 'save request');
  assert.equal(inGrid.disabled, true);
  assert.equal(main.disabled, true);
  assert.equal(inGrid.textContent, 'Saving...');
  main.click();
  await d.flush();
  assert.equal(d.saves.length, 1, 'no second save while the first is in flight');
  d.releaseSaves();
  await waitFor(() => !inGrid.disabled, 'buttons to re-enable');
  assert.equal(main.disabled, false);
  assert.equal(inGrid.textContent, 'Save');
  assert.equal(main.textContent, 'Save Settings');
});

test('successful save shows the success popup', async (t) => {
  const d = await loadDashboard();
  t.after(d.close);
  d.$('#extra-save-btn').click();
  await waitFor(() => d.$('#success-modal').style.display === 'flex', 'success popup');
});

// --- safety: never wipe extras by accident ----------------------------------

test('if settings fail to load, saving does not send (and so cannot wipe) extras', async (t) => {
  const d = await loadDashboard({ getStatus: 500 });
  t.after(d.close);
  // Failed load leaves the blank form, so the student has to pick a channel.
  if (!d.$('#ch-email').checked) d.$('#ch-email').click();
  d.$('#main-cta-btn').click();
  await waitFor(() => d.saves.length === 1, 'save request');
  assert.equal('extra_reminder_days' in d.saves[0], false);
});

test('...but if the student ticks the grid after a failed load, their ticks are sent', async (t) => {
  const d = await loadDashboard({ getStatus: 500 });
  t.after(d.close);
  if (!d.$('#ch-email').checked) d.$('#ch-email').click();
  d.cell('other', 2).click();
  d.$('#main-cta-btn').click();
  await waitFor(() => d.saves.length === 1, 'save request');
  assert.deepEqual(d.saves[0].extra_reminder_days, { other: [2] });
});

// --- regressions: old save rules still apply to both buttons -----------------

for (const btn of ['#main-cta-btn', '#extra-save-btn']) {
  test(`${btn}: no channel selected → warning, nothing saved`, async (t) => {
    const d = await loadDashboard();
    t.after(d.close);
    d.$('#ch-email').click(); // untick the only channel
    d.$(btn).click();
    await d.flush();
    assert.equal(d.saves.length, 0);
    assert.ok(d.messageShown(), 'a warning popup is shown');
  });

  test(`${btn}: SMS with a bad phone number → warning, nothing saved`, async (t) => {
    const d = await loadDashboard();
    t.after(d.close);
    d.$('#ch-sms').click();
    d.$('#sms-field').value = '123';
    d.$(btn).click();
    await d.flush();
    assert.equal(d.saves.length, 0);
    assert.ok(d.messageShown());
  });
}
