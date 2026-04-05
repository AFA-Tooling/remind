// Admin endpoint: List all deadlines
import { getDb } from '../firestore.js';
import { requireAdmin } from './auth.js';

async function handler(req, res) {
  if (req.method !== 'GET') {
    return res.status(405).json({ error: 'Method not allowed' });
  }

  try {
    const db = getDb();
    const snapshot = await db.collection('deadlines').get();

    const deadlines = snapshot.docs.map(doc => ({
      id: doc.id,
      ...doc.data()
    }));

    deadlines.sort((a, b) => {
      const da = a.due ? new Date(a.due) : new Date(0);
      const db_ = b.due ? new Date(b.due) : new Date(0);
      return da - db_;
    });

    return res.status(200).json({ success: true, data: deadlines, count: deadlines.length });
  } catch (error) {
    console.error('Error fetching deadlines:', error);
    return res.status(500).json({ error: 'Internal server error', details: error.message });
  }
}

export default requireAdmin(handler);
