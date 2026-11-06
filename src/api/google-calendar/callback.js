import { getApps } from 'firebase-admin/app';
import { getDb } from '../firestore.js';
import { exchangeCodeForTokens, getOAuthStateId, isGoogleCalendarConfigured } from './googleClient.js';

const redirectWithStatus = (res, status, reason = '') => {
  const params = new URLSearchParams({ calendar: status });
  if (reason) params.set('reason', reason);
  return res.redirect(302, `/index.html?${params}`);
};

export default async function handler(req, res) {
  if (!isGoogleCalendarConfigured()) return redirectWithStatus(res, 'error', 'not_configured');
  if (!req.query.state) return redirectWithStatus(res, 'error', 'missing_state');

  try {
    if (!getApps().length) getDb();
    const db = getDb();
    const stateRef = db.collection('google_calendar_oauth_states').doc(getOAuthStateId(req.query.state));
    const stateSnapshot = await stateRef.get();
    if (!stateSnapshot.exists) return redirectWithStatus(res, 'error', 'invalid_state');
    const state = stateSnapshot.data();
    await stateRef.delete();
    const createdAt = new Date(state.created_at).getTime();
    if (!Number.isFinite(createdAt) || Date.now() - createdAt > 10 * 60 * 1000 || createdAt > Date.now()) {
      return redirectWithStatus(res, 'error', 'expired_state');
    }
    if (req.query.error) return redirectWithStatus(res, 'error', 'consent_denied');
    if (!req.query.code) return redirectWithStatus(res, 'error', 'missing_code');
    if (!state.email) return redirectWithStatus(res, 'error', 'missing_email');

    const tokenData = await exchangeCodeForTokens(req.query.code);
    const tokenRef = db.collection('google_calendar_tokens').doc(state.email);
    const existing = await tokenRef.get();
    const existingData = existing.exists ? existing.data() : {};
    const refreshToken = tokenData.refresh_token || existingData.refresh_token;
    if (!refreshToken) return redirectWithStatus(res, 'error', 'missing_refresh_token');

    await tokenRef.set({
      access_token: tokenData.access_token,
      refresh_token: refreshToken,
      token_expires_at: new Date(Date.now() + (tokenData.expires_in || 3600) * 1000).toISOString(),
      connected_at: new Date().toISOString(),
    });
    return redirectWithStatus(res, 'connected');
  } catch (error) {
    console.error('Google Tasks OAuth callback error:', error.message);
    return redirectWithStatus(res, 'error', 'oauth_failed');
  }
}
