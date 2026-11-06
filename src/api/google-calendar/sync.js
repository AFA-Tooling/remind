import crypto from 'crypto';
import { getDb } from '../firestore.js';
import { verifyUserAuth } from '../auth/verifyUser.js';
import { getAccessToken, tasksRequest } from './googleClient.js';

const TASK_LIST_TITLE = 'AutoRemind Assignments';

function getAssignmentDue(value) {
  if (typeof value !== 'string' || !value.trim()) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date.toISOString();
}

function assignmentIdentity(assignment) {
  return assignment.html_url
    ? `${assignment.source}|${assignment.course_code}|${assignment.html_url}`
    : `${assignment.source}|${assignment.course_code}|${assignment.assignment_name}`;
}

function taskTitle(assignment) {
  return assignment.course_code
    ? `${assignment.assignment_name} (${assignment.course_code})`
    : assignment.assignment_name;
}

function taskLinkId(email, key) {
  return crypto.createHash('sha256').update(`${email}\0${key}`).digest('hex');
}

async function getTaskList(accessToken, tokenData, tokenRef) {
  if (tokenData.task_list_id) return tokenData.task_list_id;
  const lists = await tasksRequest(accessToken, 'GET', '/users/@me/lists?maxResults=100');
  let taskList = (lists.items || []).find(item => item.title === TASK_LIST_TITLE);
  if (!taskList) {
    taskList = await tasksRequest(accessToken, 'POST', '/users/@me/lists', { title: TASK_LIST_TITLE });
  }
  await tokenRef.update({ task_list_id: taskList.id });
  return taskList.id;
}

function makeTaskPayload(assignment, due, isUpdate = false) {
  return {
    title: taskTitle(assignment),
    notes: assignment.html_url ? `Assignment link: ${assignment.html_url}` : undefined,
    due,
    status: assignment.completed ? 'completed' : 'needsAction',
    ...(assignment.completed
      ? { completed: new Date().toISOString() }
      : (isUpdate ? { completed: null } : {})),
  };
}

export async function syncGoogleTasks(db, email, assignments, deps = {}) {
  const getToken = deps.getAccessToken || getAccessToken;
  const request = deps.tasksRequest || tasksRequest;
  const { accessToken, tokenData, ref: tokenRef } = await getToken(db, email);
  const taskListId = await getTaskList(accessToken, tokenData, tokenRef);
  const linksSnapshot = await db.collection('google_calendar_tasks').where('email', '==', email).get();
  const existingLinks = new Map(linksSnapshot.docs.map(doc => [doc.data().assignment_key, doc.data()]));
  let created = 0;
  let updated = 0;
  let unchanged = 0;
  let skippedWithoutDueDate = 0;

  for (const assignment of assignments) {
    const due = getAssignmentDue(assignment.due);
    if (!due) {
      skippedWithoutDueDate++;
      continue;
    }
    const key = assignmentIdentity(assignment);
    const title = taskTitle(assignment);
    const completed = !!assignment.completed;
    const linkRef = db.collection('google_calendar_tasks').doc(taskLinkId(email, key));
    const link = existingLinks.get(key);
    const sameTaskList = link && link.task_list_id === taskListId;
    if (sameTaskList && link.title === title && link.due === due && link.completed === completed) {
      unchanged++;
      continue;
    }

    const payload = makeTaskPayload(assignment, due, !!sameTaskList);
    let task;
    if (sameTaskList) {
      try {
        task = await request(accessToken, 'PATCH', `/lists/${encodeURIComponent(taskListId)}/tasks/${encodeURIComponent(link.task_id)}`, payload);
        updated++;
      } catch (error) {
        if (!error.message.includes('(404)')) throw error;
      }
    }
    if (!task) {
      task = await request(accessToken, 'POST', `/lists/${encodeURIComponent(taskListId)}/tasks`, payload);
      created++;
    }
    await linkRef.set({
      email,
      assignment_key: key,
      task_id: task.id,
      task_list_id: taskListId,
      title,
      due,
      completed,
    });
    existingLinks.set(key, {
      email,
      assignment_key: key,
      task_id: task.id,
      task_list_id: taskListId,
      title,
      due,
      completed,
    });
  }

  return { created, updated, unchanged, skippedWithoutDueDate };
}

function validateAssignments(assignments) {
  if (!Array.isArray(assignments) || assignments.length > 500) return false;
  return assignments.every(assignment =>
    assignment && typeof assignment === 'object' &&
    typeof assignment.assignment_name === 'string' &&
    assignment.assignment_name.trim().length > 0 && assignment.assignment_name.length <= 300 &&
    typeof assignment.course_code === 'string' && assignment.course_code.length <= 100 &&
    ['canvas', 'gradesync'].includes(assignment.source) &&
    (assignment.due === null || typeof assignment.due === 'string') &&
    (assignment.html_url === undefined || (
      typeof assignment.html_url === 'string' &&
      assignment.html_url.length <= 2048 &&
      (!assignment.html_url || /^https?:\/\//i.test(assignment.html_url))
    )) &&
    (assignment.completed === undefined || typeof assignment.completed === 'boolean')
  );
}

export default async function handler(req, res, deps = {}) {
  if (req.method !== 'POST') return res.status(405).json({ error: 'Method not allowed' });
  const verifyAuth = deps.verifyUserAuth || verifyUserAuth;
  const authResult = await verifyAuth(req);
  if (!authResult.authorized) return res.status(401).json({ error: authResult.error });
  if (!validateAssignments(req.body?.assignments)) {
    return res.status(400).json({ error: 'Invalid assignments payload' });
  }

  try {
    const result = await syncGoogleTasks((deps.getDb || getDb)(), authResult.email, req.body.assignments, deps);
    return res.status(200).json(result);
  } catch (error) {
    console.error('Google Tasks sync error:', error);
    return res.status(502).json({ error: 'Google Tasks sync failed', details: error.message });
  }
}
