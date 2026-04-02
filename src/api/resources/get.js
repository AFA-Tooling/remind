import { getDb } from '../firestore.js';

export default async function handler(req, res) {
  if (req.method !== 'GET') {
    return res.status(405).json({ error: 'Method not allowed' });
  }

  const assignmentName = (req.query?.assignment_name || '').trim();
  if (!assignmentName) {
    return res.status(400).json({ error: 'assignment_name is required' });
  }

  try {
    const db = getDb();
    const snapshot = await db.collection('assignment_resources')
      .where('assignment_name', '==', assignmentName)
      .get();

    const resources = snapshot.docs.map(doc => ({ id: doc.id, ...doc.data() }));

    return res.status(200).json({ success: true, data: resources });
  } catch (error) {
    return res.status(500).json({ error: 'Internal server error', details: error.message });
  }
}
