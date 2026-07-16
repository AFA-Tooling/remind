import { getDb } from '../firestore.js';
import { verifyUserAuth } from '../auth/verifyUser.js';

export default async function handler(req, res) {
    if (req.method !== 'GET') {
        return res.status(405).json({ error: 'Method not allowed' });
    }

    const authResult = await verifyUserAuth(req);
    if (!authResult.authorized) {
        return res.status(401).json({ error: authResult.error });
    }

    try {
        const loginEmail = authResult.email;

        const db = getDb();
        // Documents in 'students' collection are keyed by email
        const docSnap = await db.collection('students').doc(loginEmail).get();

        if (!docSnap.exists) {
            return res.status(404).json({ error: 'User not found' });
        }

        const data = docSnap.data();

        // Roster lookup keys on lowercased email
        const rosterSnap = await db.collection('class_roster').doc(loginEmail.toLowerCase()).get();
        const onRoster = rosterSnap.exists;

        const categoryPrefs = data.category_prefs || { lab: true, homework: true, midterm: true, quiz: true, project: true };

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
                email: data.email,
                canvas_connected: data.canvas_connected || false,
                canvas_domain: data.canvas_domain || null,
                on_roster: onRoster,
                category_prefs: {
                    lab: categoryPrefs.lab !== false,
                    homework: categoryPrefs.homework !== false,
                    midterm: categoryPrefs.midterm !== false,
                    quiz: categoryPrefs.quiz !== false,
                    project: categoryPrefs.project !== false,
                },
                project_early_reminder: data.project_early_reminder === true,
                // Opt-out: release-day notifications are on unless explicitly disabled.
                release_reminder: data.release_reminder !== false,
            }
        });

    } catch (error) {
        return res.status(500).json({ error: 'Internal server error', details: error.message });
    }
}
