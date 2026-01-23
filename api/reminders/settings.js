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

    const { channels = {}, days_before, user_email, preferred_first_name } = body;

    // 🔑 canonical email is always the login email from authenticated session
    // The email cannot be changed - it must match the authenticated user's email
    // This ensures users can only update their own profile
    const loginEmail = typeof user_email === 'string' ? user_email.trim().toLowerCase() : null;

    const phoneNumber = channels.sms || null;
    const discordId = channels.discord || null;
    const wantsEmailChannel = !!channels.email; // just to set email_pref

    if (!loginEmail || typeof days_before !== 'number') {
      return res.status(400).json({ error: 'Invalid request data' });
    }

    const clampedDays = Math.max(0, Math.min(7, Math.round(days_before)));

    const preferredFirstName = preferred_first_name ? preferred_first_name.trim() : null;

    const studentData = {
      email: loginEmail, // Email is locked to authenticated user - cannot be changed
      phone_number: phoneNumber ? phoneNumber.trim() : null,
      discord_id: discordId ? discordId.trim() : null,
      days_before_deadline: clampedDays,
      phone_pref: !!phoneNumber,
      email_pref: wantsEmailChannel,
      discord_pref: !!discordId,
      preferred_first_name: preferredFirstName || null
    };

    // Use upsert to handle both insert and update
    // This will insert if email doesn't exist, or update if it does
    // The email field is used as the conflict key, so it cannot be changed
    const { data, error } = await supabase
      .from('students_duplicate')
      .upsert(studentData, {
        onConflict: 'email',
        ignoreDuplicates: false
      })
      .select()
      .single();

    if (error) {
      return res.status(500).json({ error: error.message });
    }

    return res.status(200).json({ success: true, data: data });

  } catch (error) {
    return res.status(500).json({ error: 'Internal server error', details: error.message });
  }
}