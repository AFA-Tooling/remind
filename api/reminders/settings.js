import { createClient } from '@supabase/supabase-js';

export default async function handler(req, res) {
  if (req.method !== 'POST') {
    return res.status(405).json({ error: 'Method not allowed' });
  }

  try {
    const supabaseUrl = process.env.SUPABASE_URL;
    const supabaseKey = process.env.SUPABASE_SERVICE_ROLE_KEY;

    if (!supabaseUrl || !supabaseKey) {
      return res.status(500).json({ error: 'Server configuration error' });
    }

    const supabase = createClient(supabaseUrl, supabaseKey);

    let body = typeof req.body === 'string' ? JSON.parse(req.body) : req.body;

    const { channels = {}, days_before, user_email } = body;

    // 🔑 canonical email is always the login email
    const loginEmail = typeof user_email === 'string' ? user_email.trim() : null;

    const phoneNumber = channels.sms || null;
    const discordId = channels.discord || null;
    const wantsEmailChannel = !!channels.email; // just to set email_pref

    if (!loginEmail || typeof days_before !== 'number') {
      return res.status(400).json({ error: 'Invalid request data' });
    }

    const clampedDays = Math.max(0, Math.min(7, Math.round(days_before)));

    const studentData = {
      email: loginEmail,
      phone_number: phoneNumber ? phoneNumber.trim() : null,
      discord_id: discordId ? discordId.trim() : null,
      notif_freq_days: clampedDays,
      phone_pref: !!phoneNumber,
      email_pref: wantsEmailChannel, 
      discord_pref: !!discordId
    };

    const { data, error } = await supabase
      .from('students_duplicate')
      .insert(studentData)
      .select();

    if (error) {
      if (error.code === '23505') {
        return res.status(400).json({
          error: 'This email is already registered.',
          details: 'Duplicate entry'
        });
      }

      return res.status(500).json({ error: error.message });
    }

    return res.status(200).json({ success: true, data: data[0] });

  } catch (error) {
    return res.status(500).json({ error: 'Internal server error', details: error.message });
  }
}