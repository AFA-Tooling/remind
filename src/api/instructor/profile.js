import { getDb } from '../firestore.js';
import { verifyUserAuth } from '../auth/verifyUser.js';

export default async function handler(req, res, deps = {}) {
  if (!['GET', 'PUT'].includes(req.method)) {
    return res.status(405).json({ error: 'Method not allowed' });
  }

  const verify = deps.verifyUserAuth || verifyUserAuth;
  const dbFactory = deps.getDb || getDb;
  const auth = await verify(req);
  if (!auth.authorized) return res.status(401).json({ error: auth.error });
  if (!auth.uid) return res.status(401).json({ error: 'Authenticated user ID is missing' });

  const db = dbFactory();
  const profileRef = db.collection('user_profiles').doc(auth.uid);
  try {
    const snapshot = await profileRef.get();
    if (!snapshot.exists || snapshot.data()?.role !== 'instructor') {
      return res.status(403).json({ error: 'Instructor role required' });
    }

    if (req.method === 'GET') {
      return res.status(200).json({
        success: true,
        preferred_first_name: snapshot.data()?.preferred_first_name || '',
      });
    }

    let body;
    try {
      body = typeof req.body === 'string' ? JSON.parse(req.body || '{}') : req.body;
    } catch {
      return res.status(400).json({ error: 'Request body must be valid JSON' });
    }
    if (typeof body?.preferred_first_name !== 'string' || body.preferred_first_name.trim().length > 50) {
      return res.status(400).json({ error: 'Preferred name must be 50 characters or fewer.' });
    }
    const preferredName = body.preferred_first_name.trim();
    await profileRef.set({
      preferred_first_name: preferredName || null,
      updated_at: new Date().toISOString(),
    }, { merge: true });
    const savedSnapshot = await profileRef.get();
    const savedName = savedSnapshot.data()?.preferred_first_name || '';
    if (savedName !== preferredName) {
      throw new Error('Saved instructor name could not be verified.');
    }
    return res.status(200).json({ success: true, preferred_first_name: savedName });
  } catch (error) {
    console.error('Instructor profile request failed:', error);
    return res.status(500).json({ error: 'Could not save instructor name.' });
  }
}
