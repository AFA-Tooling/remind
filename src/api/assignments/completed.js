import { createHash } from 'node:crypto';
import { getDb } from '../firestore.js';
import { verifyUserAuth } from '../auth/verifyUser.js';

function completionDocId(assignmentKey) {
  return createHash('sha256').update(assignmentKey).digest('hex');
}

export default async function handler(req, res, deps = {}) {
  const verifyAuth = deps.verifyUserAuth || verifyUserAuth;
  const dbFactory = deps.getDb || getDb;

  if (!['GET', 'POST'].includes(req.method)) {
    return res.status(405).json({ error: 'Method not allowed' });
  }

  const authResult = await verifyAuth(req);
  if (!authResult.authorized || !authResult.email) {
    return res.status(401).json({ error: authResult.error || 'Invalid token' });
  }

  try {
    const collection = dbFactory()
      .collection('students')
      .doc(authResult.email)
      .collection('completed_assignments');

    if (req.method === 'GET') {
      const snapshot = await collection.get();
      const assignments = snapshot.docs
        .map(doc => doc.data().assignment_key)
        .filter(key => typeof key === 'string');
      return res.status(200).json({ success: true, data: assignments });
    }

    const body = typeof req.body === 'string' ? JSON.parse(req.body) : req.body;
    const { assignment_key: assignmentKey, completed } = body || {};
    if (typeof assignmentKey !== 'string' || assignmentKey.length === 0 || assignmentKey.length > 2048 || typeof completed !== 'boolean') {
      return res.status(400).json({ error: 'Invalid request data' });
    }

    const doc = collection.doc(completionDocId(assignmentKey));
    if (completed) {
      await doc.set({ assignment_key: assignmentKey, completed_at: new Date().toISOString() });
    } else {
      await doc.delete();
    }

    return res.status(200).json({ success: true });
  } catch (error) {
    return res.status(500).json({ error: 'Internal server error', details: error.message });
  }
}