// Admin endpoint: List all students
import { getDb } from '../firestore.js';
import { requireAdmin } from './auth.js';

async function handler(req, res) {
  if (req.method !== 'GET') {
    return res.status(405).json({ error: 'Method not allowed' });
  }

  try {
    const db = getDb();
    const snapshot = await db.collection('students').get();

    const students = snapshot.docs.map(doc => ({
      id: doc.id,
      ...doc.data(),
      phone_number: doc.data().phone_number
        ? '***-***-' + doc.data().phone_number.slice(-4)
        : null
    }));

    return res.status(200).json({ success: true, data: students, count: students.length });
  } catch (error) {
    console.error('Error fetching students:', error);
    return res.status(500).json({ error: 'Internal server error', details: error.message });
  }
}

export default requireAdmin(handler);
