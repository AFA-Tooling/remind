import crypto from 'crypto';
import { getApps } from 'firebase-admin/app';
import { getDb } from '../firestore.js';
import { exchangeCodeForTokens, getOAuthStateId, isGoogleCalendarConfigured } from './googleClient.js';

const OAUTH_STATE_COOKIE = 'autore_google_oauth_state';

function getCookieValue(cookieHeader, name) {
  for (const cookie of (cookieHeader || '').split(';')) {
    const separator = cookie.indexOf('=');
    if (separator < 0 || cookie.slice(0, separator).trim() !== name) continue;
    return cookie.slice(separator + 1).trim();
  }
  return null;
}

function statesMatch(queryState, cookieState) {
  if (!queryState || !cookieState) return false;
  const query = Buffer.from(queryState);
  const cookie = Buffer.from(cookieState);
  return query.length === cookie.length && crypto.timingSafeEqual(query, cookie);
}

function clearStateCookie(req, res) {
  const cookieParts = [
    `${OAUTH_STATE_COOKIE}=`,
    'Path=/api/google-calendar/callback',
    'HttpOnly',
    'SameSite=Lax',
    'Max-Age=0',
  ];
  const forwardedProto = req.headers?.['x-forwarded-proto']?.split(',')[0].trim();
  if (forwardedProto === 'https' ||
      req.socket?.encrypted ||
      process.env.GOOGLE_CALENDAR_REDIRECT_URI?.startsWith('https://')) {
    cookieParts.push('Secure');
  }
  res.setHeader('Set-Cookie', cookieParts.join('; '));
}

const redirectWithStatus = (req, res, status, reason = '') => {
  clearStateCookie(req, res);
  const params = new URLSearchParams({ calendar: status });
  if (reason) params.set('reason', reason);
  return res.redirect(302, `/index.html?${params}`);
};

export default async function handler(req, res, deps = {}) {
  if (!isGoogleCalendarConfigured()) return redirectWithStatus(req, res, 'error', 'not_configured');
  if (!req.query.state) return redirectWithStatus(req, res, 'error', 'missing_state');
  const cookieState = getCookieValue(req.headers?.cookie, OAUTH_STATE_COOKIE);
  if (!statesMatch(req.query.state, cookieState)) {
    return redirectWithStatus(req, res, 'error', 'state_mismatch');
  }

  try {
    if (!deps.getDb && !getApps().length) getDb();
    const db = (deps.getDb || getDb)();
    const stateRef = db.collection('google_calendar_oauth_states').doc(getOAuthStateId(req.query.state));
    const stateSnapshot = await stateRef.get();
    if (!stateSnapshot.exists) return redirectWithStatus(req, res, 'error', 'invalid_state');
    const state = stateSnapshot.data();
    await stateRef.delete();
    const createdAt = new Date(state.created_at).getTime();
    if (!Number.isFinite(createdAt) || Date.now() - createdAt > 10 * 60 * 1000 || createdAt > Date.now()) {
      return redirectWithStatus(req, res, 'error', 'expired_state');
    }
    if (req.query.error) return redirectWithStatus(req, res, 'error', 'consent_denied');
    if (!req.query.code) return redirectWithStatus(req, res, 'error', 'missing_code');
    if (!state.email) return redirectWithStatus(req, res, 'error', 'missing_email');

    const tokenData = await (deps.exchangeCodeForTokens || exchangeCodeForTokens)(req.query.code);
    const tokenRef = db.collection('google_calendar_tokens').doc(state.email);
    const existing = await tokenRef.get();
    const existingData = existing.exists ? existing.data() : {};
    const refreshToken = tokenData.refresh_token || existingData.refresh_token;
    if (!refreshToken) return redirectWithStatus(req, res, 'error', 'missing_refresh_token');

    await tokenRef.set({
      access_token: tokenData.access_token,
      refresh_token: refreshToken,
      token_expires_at: new Date(Date.now() + (tokenData.expires_in || 3600) * 1000).toISOString(),
      connected_at: new Date().toISOString(),
    });
    return redirectWithStatus(req, res, 'connected');
  } catch (error) {
    console.error('Google Tasks OAuth callback error:', error.message);
    return redirectWithStatus(req, res, 'error', 'oauth_failed');
  }
}
