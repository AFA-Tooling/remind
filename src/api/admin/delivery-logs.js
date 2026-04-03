// Admin endpoint: View delivery logs
import { getDb } from '../firestore.js';
import { requireAdmin } from './auth.js';

async function handler(req, res) {
  if (req.method !== 'GET') {
    return res.status(405).json({ error: 'Method not allowed' });
  }

  try {
    const db = getDb();
    const { limit = '100', status, channel, start_date, end_date } = req.query;

    let query = db.collection('message_delivery_logs')
      .orderBy('timestamp', 'desc')
      .limit(parseInt(limit, 10));

    const snapshot = await query.get();

    let logs = snapshot.docs.map(doc => ({ id: doc.id, ...doc.data() }));

    // Client-side filtering (Firestore compound query limitations)
    if (status) logs = logs.filter(l => l.status === status);
    if (channel) logs = logs.filter(l => l.channel === channel);
    if (start_date) logs = logs.filter(l => new Date(l.timestamp) >= new Date(start_date));
    if (end_date) logs = logs.filter(l => new Date(l.timestamp) <= new Date(end_date));

    const stats = {
      total: logs.length,
      sent: logs.filter(l => l.status === 'sent').length,
      failed: logs.filter(l => l.status === 'failed').length,
      by_channel: {
        email: logs.filter(l => l.channel === 'email').length,
        sms: logs.filter(l => l.channel === 'sms').length,
        discord: logs.filter(l => l.channel === 'discord').length
      }
    };

    return res.status(200).json({ success: true, data: logs, stats });
  } catch (error) {
    console.error('Error fetching delivery logs:', error);
    return res.status(500).json({ error: 'Internal server error', details: error.message });
  }
}

export default requireAdmin(handler);
