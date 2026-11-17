import { getDb } from '../firestore.js';
import { verifyUserAuth } from '../auth/verifyUser.js';

const VALID_ROLES = new Set(['student', 'instructor']);

export default async function handler(req, res, deps = {}) {
  if (!['GET', 'PUT'].includes(req.method)) {
    return res.status(405).json({ error: 'Method not allowed' });
  }

  const verify = deps.verifyUserAuth || verifyUserAuth;
  const dbFactory = deps.getDb || getDb;
  const auth = await verify(req);
  if (!auth.authorized) {
    return res.status(401).json({ error: auth.error });
  }
  if (!auth.uid) {
    return res.status(401).json({ error: 'Authenticated user ID is missing' });
  }

  const db = dbFactory();
  const profileRef = db.collection('user_profiles').doc(auth.uid);

  if (req.method === 'GET') {
    try {
      const snapshot = await profileRef.get();
      return res.status(200).json({
        success: true,
        role: snapshot.exists ? snapshot.data().role || null : null,
      });
    } catch (error) {
      console.error('Account role lookup failed:', error);
      return res.status(500).json({ error: 'Internal server error' });
    }
  }

  if (req.method === 'PUT') {
    let body;
    try {
      body = typeof req.body === 'string' ? JSON.parse(req.body || '{}') : req.body;
    } catch {
      return res.status(400).json({ error: 'Request body must be valid JSON' });
    }
    const role = body?.role;
    if (!VALID_ROLES.has(role)) {
      return res.status(400).json({ error: 'role must be student or instructor' });
    }

    try {
      const snapshot = await profileRef.get();
      const now = new Date().toISOString();
      await profileRef.set({
        email: auth.email || null,
        role,
        created_at: snapshot.exists ? snapshot.data().created_at || now : now,
        updated_at: now,
      }, { merge: true });
      return res.status(200).json({ success: true, role });
    } catch (error) {
      console.error('Account role update failed:', error);
      return res.status(500).json({ error: 'Internal server error' });
    }
  }
}
