import { getDb } from '../firestore.js';
import { sendWelcomeEmail } from '../../services/welcomeEmail.js';
import { verifyUserAuth } from '../auth/verifyUser.js';
import { getStudyStatus } from '../study/studyStatus.js';
import { LOCKOUT_MESSAGE, WAITLIST_MESSAGE } from '../study/messages.js';

export default async function handler(req, res) {
  if (req.method !== 'POST') {
    return res.status(405).json({ error: 'Method not allowed' });
  }

  const authResult = await verifyUserAuth(req);
  if (!authResult.authorized) {
    return res.status(401).json({ error: authResult.error });
  }

  try {
    // Study-gating: non-consented students may not save settings at all.
    // Waitlisted/pending students DO save (their prefs activate when access opens),
    // but the response flags them so the UI can show the waitlist popup.
    const study = await getStudyStatus(getDb(), authResult.email);
    if (study.status === 'not_consented') {
      return res.status(403).json({ error: 'Not consented', code: 'NOT_CONSENTED', message: LOCKOUT_MESSAGE });
    }
    const waitlisted = study.status === 'waitlisted' || study.status === 'pending';

    let body = typeof req.body === 'string' ? JSON.parse(req.body) : req.body;

    const { channels = {}, days_before, preferred_first_name, category_prefs, project_early_reminder, release_reminder } = body;

    const loginEmail = authResult.email;

    const phoneNumber = channels.sms || null;
    const discordId = channels.discord || null;
    const wantsEmailChannel = !!channels.email;

    if (!loginEmail || typeof days_before !== 'number') {
      return res.status(400).json({ error: 'Invalid request data' });
    }

    const clampedDays = Math.max(0, Math.min(5, Math.round(days_before)));
    const preferredFirstName = preferred_first_name ? preferred_first_name.trim() : null;

    const db = getDb();
    const docRef = db.collection('students').doc(loginEmail);

    // Check if user already exists (to detect new vs returning user)
    const existingDoc = await docRef.get();
    const existingUser = existingDoc.exists ? existingDoc.data() : null;
    const alreadySentWelcome = existingUser?.welcome_email_sent === true;

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

    if (category_prefs && typeof category_prefs === 'object') {
      studentData.category_prefs = {
        lab: !!category_prefs.lab,
        homework: !!category_prefs.homework,
        midterm: !!category_prefs.midterm,
        quiz: !!category_prefs.quiz,
        project: !!category_prefs.project,
      };
      // Roster-only: remind a day earlier for projects (early submission = extra credit).
      studentData.project_early_reminder = !!project_early_reminder;
      // Roster-only: notify on the day an assignment is released.
      studentData.release_reminder = !!release_reminder;
    }

    // Document ID = email — set(merge:true) acts as upsert
    await docRef.set(studentData, { merge: true });
    const saved = (await docRef.get()).data();

    // Send welcome email on first settings save with email enabled.
    // Skip for waitlisted students — they get no notifications yet, so a
    // "you're all set" welcome would be misleading.
    if (wantsEmailChannel && !alreadySentWelcome && !waitlisted) {
      try {
        console.log(`[Settings] Sending welcome email to new user: ${loginEmail}`);

        const welcomeResult = await sendWelcomeEmail({
          email: loginEmail,
          preferred_name: preferredFirstName || 'there',
          channels: {
            email: { enabled: wantsEmailChannel },
            sms: { enabled: !!phoneNumber, value: phoneNumber },
            discord: { enabled: !!discordId, value: discordId }
          },
          days_before: clampedDays
        });

        if (welcomeResult.success) {
          console.log(`[Settings] Welcome email sent successfully to ${loginEmail}`);
          await docRef.update({ welcome_email_sent: true });
        } else {
          console.error(`[Settings] Failed to send welcome email: ${welcomeResult.error}`);
        }
      } catch (welcomeError) {
        // Log error but don't fail the settings save
        console.error(`[Settings] Welcome email error: ${welcomeError.message}`);
      }
    }

    return res.status(200).json({
      success: true,
      data: saved,
      waitlisted,
      message: waitlisted ? WAITLIST_MESSAGE : null,
    });

  } catch (error) {
    return res.status(500).json({ error: 'Internal server error', details: error.message });
  }
}
