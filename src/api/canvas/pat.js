import { getDb } from '../firestore.js';
import { canvasFetch } from './canvasClient.js';
import { syncCanvasAssignments } from './sync.js';

const CANVAS_DEFAULT_DOMAIN = process.env.CANVAS_DEFAULT_DOMAIN || 'bcourses.berkeley.edu';

export default async function handler(req, res) {
  if (req.method !== 'POST') {
    return res.status(405).json({ error: 'Method not allowed' });
  }

  const email = (req.body.user_email || '').trim().toLowerCase();
  const pat = (req.body.pat || '').trim();

  if (!email) return res.status(400).json({ error: 'user_email is required' });
  if (!pat) return res.status(400).json({ error: 'pat is required' });

  // Validate PAT by hitting Canvas before saving anything
  try {
    await canvasFetch(CANVAS_DEFAULT_DOMAIN, pat, '/users/self/profile');
  } catch (err) {
    return res.status(400).json({
      error: 'Invalid token — check that it has the correct permissions',
      details: err.message,
    });
  }

  const db = getDb();
  const now = new Date().toISOString();

  await db.collection('canvas_tokens').doc(email).set({
    token_type: 'pat',
    canvas_domain: CANVAS_DEFAULT_DOMAIN,
    access_token: pat,
    refresh_token: null,
    token_expires_at: null,
    canvas_user_id: null,
    connected_at: now,
    last_sync_at: null,
    sync_error: null,
  });

  await db.collection('students').doc(email).set(
    { canvas_connected: true, canvas_domain: CANVAS_DEFAULT_DOMAIN },
    { merge: true }
  );

  try {
    const result = await syncCanvasAssignments(db, email);
    return res.status(200).json({ success: true, ...result });
  } catch (syncErr) {
    console.error(`Initial Canvas sync failed for ${email}:`, syncErr.message);
    await db.collection('canvas_tokens').doc(email).update({ sync_error: syncErr.message });
    return res.status(200).json({ success: true, synced: 0, removed: 0, sync_warning: syncErr.message });
  }
}
