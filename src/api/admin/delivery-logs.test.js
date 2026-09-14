import test from 'node:test';
import assert from 'node:assert/strict';

import { filterLogs, computeStats } from './delivery-logs.js';

function makeLog(channel, status, timestamp) {
  return { channel, status, timestamp, recipient: `${channel}-recipient` };
}

test('filterLogs with no filters returns everything', () => {
  const logs = [makeLog('email', 'sent', '2026-09-14T10:00:00Z'), makeLog('sms', 'failed', '2026-09-14T09:00:00Z')];
  assert.equal(filterLogs(logs).length, 2);
});

test('filterLogs by channel only returns that channel', () => {
  const logs = [
    makeLog('email', 'sent', '2026-09-14T10:00:00Z'),
    makeLog('sms', 'sent', '2026-09-14T09:00:00Z'),
    makeLog('discord', 'sent', '2026-09-14T08:00:00Z'),
  ];
  const out = filterLogs(logs, { channel: 'sms' });
  assert.equal(out.length, 1);
  assert.equal(out[0].channel, 'sms');
});

test('filterLogs by status only returns that status', () => {
  const logs = [makeLog('email', 'sent', '2026-09-14T10:00:00Z'), makeLog('email', 'failed', '2026-09-14T09:00:00Z')];
  const out = filterLogs(logs, { status: 'failed' });
  assert.equal(out.length, 1);
  assert.equal(out[0].status, 'failed');
});

test('filterLogs combines channel and status filters', () => {
  const logs = [
    makeLog('sms', 'sent', '2026-09-14T10:00:00Z'),
    makeLog('sms', 'failed', '2026-09-14T09:00:00Z'),
    makeLog('email', 'failed', '2026-09-14T08:00:00Z'),
  ];
  const out = filterLogs(logs, { channel: 'sms', status: 'failed' });
  assert.equal(out.length, 1);
  assert.equal(out[0].channel, 'sms');
  assert.equal(out[0].status, 'failed');
});

test('filterLogs respects start_date and end_date', () => {
  const logs = [
    makeLog('email', 'sent', '2026-09-14T10:00:00Z'),
    makeLog('email', 'sent', '2026-09-13T10:00:00Z'),
    makeLog('email', 'sent', '2026-09-12T10:00:00Z'),
  ];
  const out = filterLogs(logs, { start_date: '2026-09-13T00:00:00Z', end_date: '2026-09-13T23:59:59Z' });
  assert.equal(out.length, 1);
  assert.equal(out[0].timestamp, '2026-09-13T10:00:00Z');
});

test('computeStats counts totals, sent/failed, and per-channel — the exact numbers the admin dashboard cards show', () => {
  const logs = [
    makeLog('email', 'sent', 't1'),
    makeLog('email', 'failed', 't2'),
    makeLog('sms', 'sent', 't3'),
    makeLog('discord', 'sent', 't4'),
    makeLog('discord', 'failed', 't5'),
  ];
  const stats = computeStats(logs);
  assert.deepEqual(stats, {
    total: 5,
    sent: 3,
    failed: 2,
    by_channel: { email: 2, sms: 1, discord: 2 },
  });
});

test('a channel squeezed out of a page-limited window is exactly what paging back must recover', () => {
  // Regression case for the 2026-09-14 bug: a day's top-200-most-recent window
  // was 100% email (330 emails that day vs. 18 sms + 4 discord sent earlier in
  // the same run), so filtering to sms/discord on that page alone found nothing
  // even though those sends succeeded. filterLogs itself is correct — the fix
  // was giving the caller a way to fetch further pages (the `before` cursor in
  // delivery-logs.js) and accumulate before filtering, not a change here.
  const oneDayOfEmailOnlyPage = Array.from({ length: 200 }, (_, i) => makeLog('email', 'sent', `t${i}`));
  assert.equal(filterLogs(oneDayOfEmailOnlyPage, { channel: 'sms' }).length, 0);

  const withEarlierPageIncluded = [makeLog('sms', 'sent', 't-earlier'), ...oneDayOfEmailOnlyPage];
  assert.equal(filterLogs(withEarlierPageIncluded, { channel: 'sms' }).length, 1);
});
