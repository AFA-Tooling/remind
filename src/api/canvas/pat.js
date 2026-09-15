import { getDb } from '../firestore.js';
import { canvasFetch } from './canvasClient.js';
import { syncCanvasAssignments } from './sync.js';
import { verifyUserAuth } from '../auth/verifyUser.js';

const CANVAS_DEFAULT_DOMAIN = process.env.CANVAS_DEFAULT_DOMAIN || 'bcourses.berkeley.edu';

/**
 * Validate a PAT against Canvas, save it under `email`, and trigger an
 * initial sync. Pure w.r.t. its inputs (db/canvasFetch/syncCanvasAssignments
 * are all passed in), so it's testable without hitting real Canvas or a
 * real Firestore.
 */
export async function connectCanvasPat(db, email, pat, { canvasFetch: fetchFn, syncCanvasAssignments: syncFn }) {
  // Validate PAT by hitting Canvas before saving anything
  await fetchFn(CANVAS_DEFAULT_DOMAIN, pat, '/users/self/profile');

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
    return { synced: 0, removed: 0, ...(await syncFn(db, email)) };
  } catch (syncErr) {
    console.error(`Initial Canvas sync failed for ${email}:`, syncErr.message);
    await db.collection('canvas_tokens').doc(email).update({ sync_error: syncErr.message });
    return { synced: 0, removed: 0, sync_warning: syncErr.message };
  }
}

// deps is overridable only for tests — production always uses the real
// verifyUserAuth/getDb/canvasFetch/syncCanvasAssignments via the defaults below.
export default async function handler(req, res, deps = {}) {
  const verifyAuth = deps.verifyUserAuth || verifyUserAuth;
  const dbFactory = deps.getDb || getDb;
  const fetchFn = deps.canvasFetch || canvasFetch;
  const syncFn = deps.syncCanvasAssignments || syncCanvasAssignments;

  if (req.method !== 'POST') {
    return res.status(405).json({ error: 'Method not allowed' });
  }

  // The email comes from the verified token, never the request body, so a
  // PAT can only ever be linked to the account belonging to whoever is
  // actually logged in.
  const authResult = await verifyAuth(req);
  if (!authResult.authorized) {
    return res.status(401).json({ error: authResult.error });
  }
  const pat = (req.body.pat || '').trim();

  if (!pat) return res.status(400).json({ error: 'pat is required' });

  try {
    const result = await connectCanvasPat(dbFactory(), authResult.email, pat, { canvasFetch: fetchFn, syncCanvasAssignments: syncFn });
    return res.status(200).json({ success: true, ...result });
  } catch (err) {
    return res.status(400).json({
      error: 'Invalid token — check that it has the correct permissions',
      details: err.message,
    });
  }
}
