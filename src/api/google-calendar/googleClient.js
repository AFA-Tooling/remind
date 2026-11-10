import crypto from 'crypto';

const TASKS_SCOPE = 'https://www.googleapis.com/auth/tasks';
const REFRESH_BUFFER_MS = 5 * 60 * 1000;
const TASKS_API = 'https://tasks.googleapis.com/tasks/v1';

export function isGoogleCalendarConfigured() {
  return !!(process.env.GOOGLE_CALENDAR_CLIENT_ID &&
    process.env.GOOGLE_CALENDAR_CLIENT_SECRET &&
    process.env.GOOGLE_CALENDAR_REDIRECT_URI);
}

export function createOAuthState() {
  return crypto.randomBytes(32).toString('base64url');
}

export function getOAuthStateId(state) {
  return crypto.createHash('sha256').update(state).digest('hex');
}

export function createAuthorizationUrl(state) {
  const { clientId, redirectUri } = getConfig();
  const url = new URL('https://accounts.google.com/o/oauth2/v2/auth');
  url.searchParams.set('client_id', clientId);
  url.searchParams.set('redirect_uri', redirectUri);
  url.searchParams.set('response_type', 'code');
  url.searchParams.set('scope', TASKS_SCOPE);
  url.searchParams.set('access_type', 'offline');
  url.searchParams.set('prompt', 'consent');
  url.searchParams.set('state', state);
  return url.toString();
}

export async function exchangeCodeForTokens(code) {
  const { clientId, clientSecret, redirectUri } = getConfig();
  const response = await fetch('https://oauth2.googleapis.com/token', {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({
      code,
      client_id: clientId,
      client_secret: clientSecret,
      redirect_uri: redirectUri,
      grant_type: 'authorization_code',
    }),
  });
  if (!response.ok) {
    throw new Error(`Google token exchange failed (${response.status})`);
  }
  return response.json();
}

async function refreshAccessToken(refreshToken) {
  const { clientId, clientSecret } = getConfig();
  const response = await fetch('https://oauth2.googleapis.com/token', {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({
      client_id: clientId,
      client_secret: clientSecret,
      refresh_token: refreshToken,
      grant_type: 'refresh_token',
    }),
  });
  if (!response.ok) {
    throw new Error(`Google token refresh failed (${response.status}); reconnect Google Tasks`);
  }
  return response.json();
}

export async function getAccessToken(db, email) {
  const ref = db.collection('google_calendar_tokens').doc(email);
  const snapshot = await ref.get();
  if (!snapshot.exists) throw new Error('Google Tasks is not connected');

  const tokenData = snapshot.data();
  if (Date.now() < new Date(tokenData.token_expires_at).getTime() - REFRESH_BUFFER_MS) {
    return { accessToken: tokenData.access_token, tokenData, ref };
  }
  if (!tokenData.refresh_token) {
    throw new Error('Google Tasks authorization expired; reconnect Google Tasks');
  }

  const refreshed = await refreshAccessToken(tokenData.refresh_token);
  const expiresAt = new Date(Date.now() + (refreshed.expires_in || 3600) * 1000).toISOString();
  await ref.update({
    access_token: refreshed.access_token,
    token_expires_at: expiresAt,
  });
  return {
    accessToken: refreshed.access_token,
    tokenData: { ...tokenData, access_token: refreshed.access_token, token_expires_at: expiresAt },
    ref,
  };
}

export async function tasksRequest(accessToken, method, path, body) {
  const response = await fetch(`${TASKS_API}${path}`, {
    method,
    headers: {
      Authorization: `Bearer ${accessToken}`,
      ...(body ? { 'Content-Type': 'application/json' } : {}),
    },
    ...(body ? { body: JSON.stringify(body) } : {}),
  });

  if (response.status === 204) return null;
  const data = await response.json();
  if (!response.ok) {
    const message = data.error?.message || response.statusText;
    throw new Error(`Google Tasks API error (${response.status}): ${message}`);
  }
  return data;
}

export async function revokeToken(refreshToken) {
  const response = await fetch('https://oauth2.googleapis.com/revoke', {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({ token: refreshToken }),
  });
  if (!response.ok) throw new Error(`Google token revocation failed (${response.status})`);
}

function getConfig() {
  return {
    clientId: process.env.GOOGLE_CALENDAR_CLIENT_ID,
    clientSecret: process.env.GOOGLE_CALENDAR_CLIENT_SECRET,
    redirectUri: process.env.GOOGLE_CALENDAR_REDIRECT_URI,
  };
}

export { TASKS_SCOPE };
