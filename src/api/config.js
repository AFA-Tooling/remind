// API endpoint to serve Firebase public credentials
// Firebase client-side credentials are safe to expose
export default async function handler(req, res) {
  // Enable CORS
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');

  // Handle preflight
  if (req.method === 'OPTIONS') {
    return res.status(200).end();
  }

  // Only allow GET requests
  if (req.method !== 'GET') {
    return res.status(405).json({ error: 'Method not allowed' });
  }

  const firebaseApiKey = process.env.FIREBASE_API_KEY || '';
  const firebaseAuthDomain = process.env.FIREBASE_AUTH_DOMAIN || '';
  const firebaseProjectId = process.env.FIREBASE_PROJECT_ID || '';

  if (!firebaseApiKey || !firebaseAuthDomain) {
    console.error('Missing Firebase environment variables');
    return res.status(500).json({
      error: 'Server configuration error',
      message: 'Firebase credentials not configured'
    });
  }

  // Return public credentials (safe to expose)
  return res.status(200).json({
    FIREBASE_API_KEY: firebaseApiKey,
    FIREBASE_AUTH_DOMAIN: firebaseAuthDomain,
    FIREBASE_PROJECT_ID: firebaseProjectId,
  });
}
