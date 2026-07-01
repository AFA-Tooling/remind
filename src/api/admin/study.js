// Admin endpoints for research-study management.
// Single handler dispatched on req.query.action (all under /api/admin/study).
//
//   GET   ?action=overview (default)  -> config + participants + counts
//   POST  ?action=consent  { emails:[...], source }  -> merge/add consented students
//   POST  ?action=remove   { email }                 -> remove a participant
//   POST  ?action=group    { email, group }          -> manually set a student's group
//   POST  ?action=randomize                          -> ~50/50 split of unassigned
//   GET   ?action=export&group=1|2                   -> { emails: [...] } for that group
//   POST  ?action=open-access { confirm: true }      -> grant Group 1 + Group 2 access
//   POST  ?action=close-access { confirm: true }     -> revert to group-gated access (undo open-access)
//
// CSV parsing for upload and CSV generation for export happen client-side; this
// endpoint speaks JSON only.

import { getDb } from '../firestore.js';
import { requireAdmin } from './auth.js';
import {
  STUDY_PARTICIPANTS,
  STUDY_CONFIG,
  STUDY_CONFIG_DOC,
  getStudyConfig,
  deriveStatus,
} from '../study/studyStatus.js';
import { assignBalanced } from '../study/randomize.js';

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

function normalizeEmail(value) {
  const e = String(value || '').trim().toLowerCase();
  return EMAIL_RE.test(e) ? e : null;
}

function nowIso() {
  return new Date().toISOString();
}

// Commit writes in chunks well under Firestore's 500-op batch limit.
async function commitInBatches(db, ops) {
  const CHUNK = 400;
  for (let i = 0; i < ops.length; i += CHUNK) {
    const batch = db.batch();
    for (const op of ops.slice(i, i + CHUNK)) op(batch);
    await batch.commit();
  }
}

async function loadParticipants(db) {
  const snap = await db.collection(STUDY_PARTICIPANTS).get();
  return snap.docs.map(d => ({
    email: d.id,
    group: d.data().group ?? null,
    source: d.data().source || null,
  }));
}

function countGroups(participants) {
  let group1 = 0, group2 = 0, unassigned = 0;
  for (const p of participants) {
    if (p.group === 1) group1++;
    else if (p.group === 2) group2++;
    else unassigned++;
  }
  return { total: participants.length, group1, group2, unassigned };
}

// Core logic with an injectable db, so the full orchestration is unit-testable
// against an in-memory fake Firestore (the default path uses the shared client).
export async function runStudyAction(req, res, db = getDb()) {
  const action = (req.query?.action || 'overview').toLowerCase();

  try {
    // ---- GET overview ----
    if (req.method === 'GET' && action === 'overview') {
      const [participants, config] = await Promise.all([loadParticipants(db), getStudyConfig(db)]);
      const data = participants
        .map(p => ({ ...p, status: deriveStatus({ consented: true, group: p.group, access_open: config.access_open }).status }))
        .sort((a, b) => a.email.localeCompare(b.email));
      return res.status(200).json({ success: true, config, counts: countGroups(participants), participants: data });
    }

    // ---- GET export ----
    if (req.method === 'GET' && action === 'export') {
      const group = Number(req.query?.group);
      if (group !== 1 && group !== 2) {
        return res.status(400).json({ error: 'group must be 1 or 2' });
      }
      const participants = await loadParticipants(db);
      const emails = participants.filter(p => p.group === group).map(p => p.email).sort();
      return res.status(200).json({ success: true, group, emails, count: emails.length });
    }

    // ---- POST consent (add/merge) ----
    if (req.method === 'POST' && action === 'consent') {
      const rawList = Array.isArray(req.body?.emails) ? req.body.emails : [];
      const source = req.body?.source === 'csv' ? 'csv' : 'manual';

      // `skipped` counts invalid-format entries only; in-list duplicates are
      // silently merged by the Set rather than reported as skipped.
      const normalized = rawList.map(normalizeEmail);
      const skipped = normalized.filter(e => !e).length;
      const cleaned = [...new Set(normalized.filter(Boolean))];
      if (cleaned.length === 0) {
        return res.status(200).json({ success: true, added: 0, alreadyPresent: 0, skipped, assigned: 0 });
      }

      const [participants, config] = await Promise.all([loadParticipants(db), getStudyConfig(db)]);
      const existing = new Map(participants.map(p => [p.email, p]));

      const toAdd = cleaned.filter(e => !existing.has(e));
      const alreadyPresent = cleaned.length - toAdd.length;

      // Auto-assign groups for newcomers only if randomization already happened.
      let assignments = new Map();
      if (config.randomized && toAdd.length) {
        const { group1, group2 } = countGroups(participants);
        for (const { email, group } of assignBalanced(toAdd, group1, group2)) {
          assignments.set(email, group);
        }
      }

      const ts = nowIso();
      const ops = toAdd.map(email => (batch) => {
        batch.set(db.collection(STUDY_PARTICIPANTS).doc(email), {
          email,
          group: assignments.has(email) ? assignments.get(email) : null,
          source,
          created_at: ts,
          updated_at: ts,
        });
      });
      await commitInBatches(db, ops);

      return res.status(200).json({
        success: true,
        added: toAdd.length,
        alreadyPresent,
        skipped,
        assigned: assignments.size,
      });
    }

    // ---- POST remove ----
    if (req.method === 'POST' && action === 'remove') {
      const email = normalizeEmail(req.body?.email);
      if (!email) return res.status(400).json({ error: 'valid email required' });
      await db.collection(STUDY_PARTICIPANTS).doc(email).delete();
      return res.status(200).json({ success: true, removed: email });
    }

    // ---- POST group (manual assignment) ----
    if (req.method === 'POST' && action === 'group') {
      const email = normalizeEmail(req.body?.email);
      const group = req.body?.group === null ? null : Number(req.body?.group);
      if (!email) return res.status(400).json({ error: 'valid email required' });
      if (group !== 1 && group !== 2 && group !== null) {
        return res.status(400).json({ error: 'group must be 1, 2, or null' });
      }
      const ref = db.collection(STUDY_PARTICIPANTS).doc(email);
      if (!(await ref.get()).exists) {
        return res.status(404).json({ error: 'participant not found' });
      }
      await ref.set({ group, updated_at: nowIso() }, { merge: true });
      return res.status(200).json({ success: true, email, group });
    }

    // ---- POST randomize ----
    if (req.method === 'POST' && action === 'randomize') {
      const participants = await loadParticipants(db);
      const { group1, group2 } = countGroups(participants);
      const unassigned = participants.filter(p => p.group !== 1 && p.group !== 2).map(p => p.email);

      const assignments = assignBalanced(unassigned, group1, group2);
      const ts = nowIso();
      const ops = assignments.map(({ email, group }) => (batch) => {
        batch.set(db.collection(STUDY_PARTICIPANTS).doc(email), { group, updated_at: ts }, { merge: true });
      });
      // Always flip randomized=true so future consenters auto-assign, even if
      // there were no unassigned students at the time.
      ops.push((batch) => {
        batch.set(db.collection(STUDY_CONFIG).doc(STUDY_CONFIG_DOC), { randomized: true, updated_at: ts }, { merge: true });
      });
      await commitInBatches(db, ops);

      return res.status(200).json({ success: true, assigned: assignments.length, counts: countGroups(participants.map(p => ({
        ...p,
        group: p.group ?? assignments.find(a => a.email === p.email)?.group ?? null,
      }))) });
    }

    // ---- POST open-access ----
    if (req.method === 'POST' && action === 'open-access') {
      if (req.body?.confirm !== true) {
        return res.status(400).json({ error: 'confirm:true required to open access to everyone' });
      }
      await db.collection(STUDY_CONFIG).doc(STUDY_CONFIG_DOC).set(
        { access_open: true, updated_at: nowIso() },
        { merge: true }
      );
      return res.status(200).json({ success: true, access_open: true });
    }

    // ---- POST close-access (undo open-access) ----
    if (req.method === 'POST' && action === 'close-access') {
      if (req.body?.confirm !== true) {
        return res.status(400).json({ error: 'confirm:true required to close access back to group-gated' });
      }
      await db.collection(STUDY_CONFIG).doc(STUDY_CONFIG_DOC).set(
        { access_open: false, updated_at: nowIso() },
        { merge: true }
      );
      return res.status(200).json({ success: true, access_open: false });
    }

    return res.status(400).json({ error: `Unknown action '${action}' for ${req.method}` });
  } catch (error) {
    console.error('Admin study error:', error);
    return res.status(500).json({ error: 'Internal server error', details: error.message });
  }
}

export default requireAdmin((req, res) => runStudyAction(req, res));
