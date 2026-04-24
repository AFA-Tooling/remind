import { getDb } from '../firestore.js';
import { verifyState, exchangeCodeForTokens, getValidToken, canvasFetch } from './canvasClient.js';
import { syncCanvasAssignments } from './sync.js';

export default async function handler(req, res) {
  const code = req.query.code;
  const stateParam = req.query.state;
  const error = req.query.error;

  // Canvas may redirect with an error
  if (error) {
    return res.redirect(302, `/index.html?canvas=error&reason=${encodeURIComponent(error)}`);
  }

  if (!code || !stateParam) {
    return res.redirect(302, '/index.html?canvas=error&reason=missing_params');
  }

  // Verify state
  const payload = verifyState(stateParam);
  if (!payload) {
    return res.redirect(302, '/index.html?canvas=error&reason=invalid_state');
  }

  const { email, domain } = payload;
  const redirectUri = process.env.CANVAS_REDIRECT_URI;

  try {
    // Exchange code for tokens
    const tokenData = await exchangeCodeForTokens(domain, code, redirectUri);

    const now = new Date().toISOString();
    const expiresAt = new Date(Date.now() + (tokenData.expires_in || 3600) * 1000).toISOString();

    const db = getDb();

    // Fetch Canvas user profile to get user ID
    let canvasUserId = null;
    try {
      const profile = await canvasFetch(domain, tokenData.access_token, '/users/self/profile');
      canvasUserId = profile.id;
    } catch {
      // Non-critical, continue without user ID
    }

    // Store tokens
    await db.collection('canvas_tokens').doc(email).set({
      canvas_domain: domain,
      access_token: tokenData.access_token,
      refresh_token: tokenData.refresh_token,
      token_expires_at: expiresAt,
      canvas_user_id: canvasUserId,
      connected_at: now,
      last_sync_at: null,
      sync_error: null,
    });

    // Update student doc
    await db.collection('students').doc(email).set(
      { canvas_connected: true, canvas_domain: domain },
      { merge: true }
    );

    // Trigger initial sync
    try {
      await syncCanvasAssignments(db, email);
    } catch (syncErr) {
      console.error(`Initial Canvas sync failed for ${email}:`, syncErr.message);
      await db.collection('canvas_tokens').doc(email).update({
        sync_error: syncErr.message,
      });
    }

    return res.redirect(302, '/index.html?canvas=connected');
  } catch (err) {
    console.error('Canvas OAuth callback error:', err);
    return res.redirect(302, `/index.html?canvas=error&reason=${encodeURIComponent(err.message)}`);
  }
}
