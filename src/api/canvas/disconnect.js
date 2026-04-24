import { getDb } from '../firestore.js';

export default async function handler(req, res) {
  if (req.method !== 'POST') {
    return res.status(405).json({ error: 'Method not allowed' });
  }

  const email = (req.body.user_email || '').trim().toLowerCase();
  if (!email) {
    return res.status(400).json({ error: 'user_email is required' });
  }

  try {
    const db = getDb();

    // Delete canvas token
    await db.collection('canvas_tokens').doc(email).delete();

    // Delete all canvas_deadlines for this user
    const deadlinesSnap = await db.collection('canvas_deadlines')
      .where('email', '==', email)
      .get();

    if (!deadlinesSnap.empty) {
      const batch = db.batch();
      let count = 0;
      for (const doc of deadlinesSnap.docs) {
        batch.delete(doc.ref);
        count++;
        // Firestore batch limit is 500
        if (count >= 500) {
          await batch.commit();
          count = 0;
        }
      }
      if (count > 0) {
        await batch.commit();
      }
    }

    // Update student doc
    await db.collection('students').doc(email).set(
      { canvas_connected: false, canvas_domain: null },
      { merge: true }
    );

    return res.status(200).json({ success: true });
  } catch (err) {
    console.error('Canvas disconnect error:', err);
    return res.status(500).json({ error: 'Internal server error', details: err.message });
  }
}
