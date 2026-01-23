import { createClient } from '@supabase/supabase-js';

export default async function handler(req, res) {
    if (req.method !== 'GET') {
        return res.status(405).json({ error: 'Method not allowed' });
    }

    try {
        const supabaseUrl = process.env.SUPABASE_URL;
        const supabaseKey = process.env.SUPABASE_SERVICE_ROLE_KEY;

        if (!supabaseUrl || !supabaseKey) {
            return res.status(500).json({ error: 'Server configuration error' });
        }

        const supabase = createClient(supabaseUrl, supabaseKey);

        // Get user_email from query parameters
        const userEmail = req.query.user_email;

        if (!userEmail || typeof userEmail !== 'string') {
            return res.status(400).json({ error: 'user_email query parameter is required' });
        }

        const loginEmail = userEmail.trim().toLowerCase();

        // Query students_duplicate table by email
        const { data, error } = await supabase
            .from('students_duplicate')
            .select('preferred_first_name, phone_number, discord_id, days_before_deadline, email_pref, phone_pref, discord_pref, email')
            .eq('email', loginEmail)
            .single();

        if (error) {
            if (error.code === 'PGRST116') {
                // No rows returned (user not found)
                return res.status(404).json({ error: 'User not found' });
            }
            return res.status(500).json({ error: error.message });
        }

        if (!data) {
            return res.status(404).json({ error: 'User not found' });
        }

        // Return user data
        return res.status(200).json({
            success: true,
            data: {
                preferred_first_name: data.preferred_first_name || null,
                phone_number: data.phone_number || null,
                discord_id: data.discord_id || null,
                days_before_deadline: data.days_before_deadline || 0,
                email_pref: data.email_pref || false,
                phone_pref: data.phone_pref || false,
                discord_pref: data.discord_pref || false,
                email: data.email
            }
        });

    } catch (error) {
        return res.status(500).json({ error: 'Internal server error', details: error.message });
    }
}

