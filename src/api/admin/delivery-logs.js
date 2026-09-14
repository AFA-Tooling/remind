// Admin endpoint: View delivery logs
import { getDb } from '../firestore.js';
import { requireAdmin } from './auth.js';

/** Pure filtering (no I/O) so it's unit-testable without faking Firestore's query chain. */
export function filterLogs(logs, { status, channel, start_date, end_date } = {}) {
  let out = logs;
  if (status) out = out.filter(l => l.status === status);
  if (channel) out = out.filter(l => l.channel === channel);
  if (start_date) out = out.filter(l => new Date(l.timestamp) >= new Date(start_date));
  if (end_date) out = out.filter(l => new Date(l.timestamp) <= new Date(end_date));
  return out;
}

export function computeStats(logs) {
  return {
    total: logs.length,
    sent: logs.filter(l => l.status === 'sent').length,
    failed: logs.filter(l => l.status === 'failed').length,
    by_channel: {
      email: logs.filter(l => l.channel === 'email').length,
      sms: logs.filter(l => l.channel === 'sms').length,
      discord: logs.filter(l => l.channel === 'discord').length
    }
  };
}

async function handler(req, res) {
  if (req.method !== 'GET') {
    return res.status(405).json({ error: 'Method not allowed' });
  }

  try {
    const db = getDb();
    const { limit = '100', status, channel, start_date, end_date, before } = req.query;
    const pageSize = parseInt(limit, 10);

    // channel/status/date filters stay client-side (compound where+orderBy needs a
    // composite index this project doesn't have), but pagination is real: `before`
    // (the oldest timestamp from the previous page) lets the admin page back through
    // history instead of only ever seeing the single most recent `limit` logs across
    // ALL channels. That matters because channels aren't interleaved evenly — the
    // daily job sends Discord, then SMS, then Email, so on a day with hundreds of
    // emails the top `limit` window can be 100% email with SMS/Discord pushed
    // entirely out of view even though they sent fine; paging back surfaces them.
    let query = db.collection('message_delivery_logs')
      .orderBy('timestamp', 'desc')
      .limit(pageSize);
    if (before) query = query.startAfter(before);

    const snapshot = await query.get();

    const rawLogs = snapshot.docs.map(doc => ({ id: doc.id, ...doc.data() }));
    // Cursor for the next page, from the unfiltered page (so paging further back
    // keeps working even when a filter hides everything on the current page).
    const nextCursor = rawLogs.length === pageSize ? rawLogs[rawLogs.length - 1].timestamp : null;

    const logs = filterLogs(rawLogs, { status, channel, start_date, end_date });

    return res.status(200).json({ success: true, data: logs, stats: computeStats(logs), next_cursor: nextCursor });
  } catch (error) {
    console.error('Error fetching delivery logs:', error);
    return res.status(500).json({ error: 'Internal server error', details: error.message });
  }
}

export default requireAdmin(handler);
