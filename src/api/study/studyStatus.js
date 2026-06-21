// Shared study-gating logic. The pure `deriveStatus` function is the single
// source of truth for the access rule; `getStudyStatus` wraps it with a Firestore
// read so endpoints don't each re-implement the rule.
//
// Status values:
//   'not_consented' — email not in study_participants
//   'pending'       — consented but group not yet assigned (no access, no popup-by-default)
//   'waitlisted'    — consented, group 2, access not yet open
//   'active'        — consented and (group 1 OR access_open)
//
// Access rule (the CRITICAL invariant for who may receive notifications):
//   hasAccess = consented AND (group === 1 OR access_open === true)

import { getDb } from '../firestore.js';

export const STUDY_CONFIG_DOC = 'state';
export const STUDY_PARTICIPANTS = 'study_participants';
export const STUDY_CONFIG = 'study_config';

/**
 * Pure status derivation — no I/O. Unit-testable.
 * @param {{ consented: boolean, group: (1|2|null), access_open: boolean }} input
 * @returns {{ consented: boolean, group: (1|2|null), access_open: boolean, hasAccess: boolean, status: string }}
 */
export function deriveStatus({ consented, group, access_open }) {
  const open = access_open === true;
  if (!consented) {
    return { consented: false, group: null, access_open: open, hasAccess: false, status: 'not_consented' };
  }
  const g = group === 1 || group === 2 ? group : null;
  const hasAccess = g === 1 || open;
  let status;
  if (hasAccess) status = 'active';
  else if (g === 2) status = 'waitlisted';
  else status = 'pending';
  return { consented: true, group: g, access_open: open, hasAccess, status };
}

/** Read the singleton study config doc, defaulting to a not-randomized / closed study. */
export async function getStudyConfig(db) {
  const snap = await db.collection(STUDY_CONFIG).doc(STUDY_CONFIG_DOC).get();
  const data = snap.exists ? snap.data() : {};
  return {
    randomized: data.randomized === true,
    access_open: data.access_open === true,
  };
}

/**
 * Resolve a single student's study status from Firestore.
 * @param {import('firebase-admin/firestore').Firestore} db
 * @param {string} email
 */
export async function getStudyStatus(db, email) {
  const key = (email || '').trim().toLowerCase();
  if (!key) return deriveStatus({ consented: false, group: null, access_open: false });

  const [participantSnap, config] = await Promise.all([
    db.collection(STUDY_PARTICIPANTS).doc(key).get(),
    getStudyConfig(db),
  ]);

  if (!participantSnap.exists) {
    return deriveStatus({ consented: false, group: null, access_open: config.access_open });
  }
  const group = participantSnap.data().group ?? null;
  return deriveStatus({ consented: true, group, access_open: config.access_open });
}

/** Convenience wrapper using the shared db singleton. */
export async function getStudyStatusForEmail(email) {
  return getStudyStatus(getDb(), email);
}
