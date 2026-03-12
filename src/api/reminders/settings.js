import { getDb } from '../firestore.js';

export default async function handler(req, res) {
  if (req.method !== 'POST') {
    return res.status(405).json({ error: 'Method not allowed' });
  }

  try {
    let body = typeof req.body === 'string' ? JSON.parse(req.body) : req.body;

    const { channels = {}, days_before, user_email, preferred_first_name } = body;

    // 🔑 canonical email is always the login email from authenticated session
    const loginEmail = typeof user_email === 'string' ? user_email.trim().toLowerCase() : null;

    const phoneNumber = channels.sms || null;
    const discordId = channels.discord || null;
    const wantsEmailChannel = !!channels.email;

    if (!loginEmail || typeof days_before !== 'number') {
      return res.status(400).json({ error: 'Invalid request data' });
    }

    const clampedDays = Math.max(0, Math.min(7, Math.round(days_before)));
    const preferredFirstName = preferred_first_name ? preferred_first_name.trim() : null;

    const studentData = {
      email: loginEmail,
      phone_number: phoneNumber ? phoneNumber.trim() : null,
      discord_id: discordId ? discordId.trim() : null,
      days_before_deadline: clampedDays,
      phone_pref: !!phoneNumber,
      email_pref: wantsEmailChannel,
      discord_pref: !!discordId,
      preferred_first_name: preferredFirstName || null,
      updated_at: new Date().toISOString(),
    };

    const db = getDb();
    // Document ID = email — set(merge:true) acts as upsert
    const docRef = db.collection('students').doc(loginEmail);
    await docRef.set(studentData, { merge: true });
    const saved = (await docRef.get()).data();

    return res.status(200).json({ success: true, data: saved });

  } catch (error) {
    return res.status(500).json({ error: 'Internal server error', details: error.message });
  }
}