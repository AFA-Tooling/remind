
import { createClient } from '@supabase/supabase-js';

export default async function handler(req, res) {
    if (req.method !== 'POST') {
        return res.status(405).json({ error: 'Method not allowed' });
    }

    try {
        const supabaseUrl = process.env.SUPABASE_URL;
        const supabaseKey = process.env.SUPABASE_SERVICE_ROLE_KEY;

        if (!supabaseUrl || !supabaseKey) {
            console.error('Server configuration error: Missing Supabase credentials');
            return res.status(500).json({ error: 'Server configuration error' });
        }

        const supabase = createClient(supabaseUrl, supabaseKey);

        let body = req.body;
        if (typeof body === 'string') {
            try {
                body = JSON.parse(body);
            } catch (e) {
                return res.status(400).json({ error: 'Invalid JSON body' });
            }
        }

        const { platforms = [], user_email, email } = body;
        // Prefer user_email, fallback to email
        const targetEmail = (user_email || email);

        if (!targetEmail || typeof targetEmail !== 'string') {
            return res.status(400).json({ error: 'Missing user email in request' });
        }

        const updates = {};
        const platformList = Array.isArray(platforms) ? platforms : [platforms];

        if (platformList.includes('all')) {
            updates.email_pref = false;
            updates.phone_pref = false;
            updates.discord_pref = false;
        } else {
            if (platformList.includes('email')) updates.email_pref = false;
            if (platformList.includes('sms')) updates.phone_pref = false;
            if (platformList.includes('discord')) updates.discord_pref = false;
        }

        if (Object.keys(updates).length === 0 && platformList.length > 0) {
            // Platforms provided but none matched known keys? 
            // Or empty list?
            // If empty list, do nothing?
            // If platform list has items but no updates, maybe invalid items.
            // But for now let's just proceed.
        }

        // Perform UPDATE
        const { data, error } = await supabase
            .from('students_duplicate')
            .update(updates)
            .eq('email', targetEmail)
            .select();

        if (error) {
            console.error('Supabase update error:', error);
            return res.status(500).json({ error: error.message });
        }

        return res.status(200).json({ success: true, message: 'Unsbscribed successfully', data });

    } catch (error) {
        console.error('Unsubscribe handler error:', error);
        return res.status(500).json({ error: 'Internal server error', details: error.message });
    }
}
