import { getDb } from '../firestore.js';

// Creates a minimal student document on first login (idempotent — no-op if already exists).
export default async function handler(req, res) {
  if (req.method !== 'POST') {
    return res.status(405).json({ error: 'Method not allowed' });
  }

  try {
    let body = typeof req.body === 'string' ? JSON.parse(req.body) : req.body;
    const { user_email, display_name } = body || {};

    const loginEmail = typeof user_email === 'string' ? user_email.trim().toLowerCase() : null;
    if (!loginEmail) {
      return res.status(400).json({ error: 'user_email is required' });
    }

    const db = getDb();
    const docRef = db.collection('students').doc(loginEmail);
    const existing = await docRef.get();

    if (existing.exists) {
      return res.status(200).json({ success: true, created: false, data: existing.data() });
    }

    const newStudent = {
      email: loginEmail,
      preferred_first_name: display_name ? display_name.split(' ')[0] : null,
      phone_number: null,
      discord_id: null,
      days_before_deadline: 1,
      email_pref: false,
      phone_pref: false,
      discord_pref: false,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    };

    await docRef.set(newStudent);
    return res.status(201).json({ success: true, created: true, data: newStudent });

  } catch (error) {
    return res.status(500).json({ error: 'Internal server error', details: error.message });
  }
}
