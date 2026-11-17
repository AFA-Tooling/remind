/**
 * Combines Gradescope and course-website assignments that describe the same deadline.
 * Gradescope wins on title/date/link; items match on kind + number ("Homework 3").
 * Combined items keep their sources in `merged_versions`; if dates disagree, due is null.
 */

const KINDS = [
  ['mini-midterm', 'mini[- ]?midterm'],
  ['midterm', 'midterm|mt'],
  ['homework', 'homework|hw'],
  ['discussion', 'discussion|disc'],
  ['lab', 'lab'],
  ['project', 'project|proj'],
  ['quiz', 'quiz'],
  ['problem set', 'problem[- ]?set|pset'],
  ['worksheet', 'worksheet'],
  ['assignment', 'assignment'],
  ['exam', 'exam'],
  ['postterm', 'post[- ]?term'],
  ['quest', 'quest'],
];
const KIND_WITH_NUMBER = new RegExp(
  `\\b(${KINDS.map(([, pattern]) => `(?:${pattern})`).join('|')})(\\s+part)?[\\s\\-#_]*0*(\\d+[a-z]?)\\b`,
  'i',
);
const QUALIFIER = /\b(checkpoint\s*\d*[a-z]?|part\s*\d+[a-z]?|retake|make-?up|design doc|proposal|milestone\s*\d*)\b/i;

function kindName(raw) {
  const found = KINDS.find(([, pattern]) => new RegExp(`^(?:${pattern})$`, 'i').test(raw));
  return found ? found[0] : raw.toLowerCase();
}

/** "Coding HW3: IntLists" -> "homework 3"; "Project 1 Checkpoint 2" -> "project 1 checkpoint 2". */
export function assignmentKey(title) {
  const text = String(title || '').replace(/\s+/g, ' ').trim();
  const match = KIND_WITH_NUMBER.exec(text);
  if (match) {
    const number = match[3].toLowerCase();
    const part = match[2] ? ' part' : '';
    const qualifier = QUALIFIER.exec(text.slice(match.index + match[0].length));
    return `${kindName(match[1])}${part} ${number}${qualifier ? ` ${qualifier[1].toLowerCase().replace(/\s+/g, ' ')}` : ''}`;
  }
  if (/\bfinal(\s+exam)?$/i.test(text) || /\bfinal exam\b/i.test(text)) return 'final exam';
  return null;
}

const TOPIC_QUALIFIER = /\b(checkpoint|milestone|part)\s*(\d*)\b/i;
const TOPIC_STOPWORDS = new Set(['project', 'proj', 'assignment', 'the', 'a', 'an', 'of']);

/** "Checkpoint" and "Checkpoint 1" name one part when the other side gives no number. */
function topicPart(text) {
  const match = TOPIC_QUALIFIER.exec(text);
  return match ? { kind: match[1].toLowerCase(), number: match[2] || '' } : null;
}

function samePart(a, b) {
  if (!a || !b) return !a && !b;
  return a.kind === b.kind && (a.number === b.number || !a.number || !b.number || (a.number === '1' && !b.number));
}

function topicWords(text) {
  return String(text || '').toLowerCase()
    .replace(TOPIC_QUALIFIER, ' ')
    .split(/[^a-z0-9]+/)
    .filter(word => word && !TOPIC_STOPWORDS.has(word))
    .join(' ');
}

/**
 * A Gradescope item named by its topic ("Hog", "Hog Checkpoint") and the website item
 * whose own page is that topic ("Project 1" linking to /projects/hog/) are one deadline
 * when the part (checkpoint or none) and the due day agree.
 */
function topicMatches(gradescopeItem, websiteItem) {
  if (assignmentKey(gradescopeItem.title)) return false; // numbered: matched by number
  let path;
  try {
    path = new URL(websiteItem.html_url || '').pathname;
  } catch {
    return false;
  }
  const segments = path.split('/').filter(Boolean);
  if (segments.length < 2) return false; // the course's own page, not the item's
  const slug = topicWords(segments[segments.length - 1].replace(/\.html?$/i, '').replace(/[-_]/g, ' '));
  const topic = topicWords(gradescopeItem.title);
  if (!slug || slug !== topic) return false;
  if (!samePart(topicPart(gradescopeItem.title), topicPart(websiteItem.title))) return false;
  const [gradescopeDay, websiteDay] = [dueDay(gradescopeItem.due), dueDay(websiteItem.due)];
  return Boolean(gradescopeDay && websiteDay && gradescopeDay === websiteDay);
}

/** The calendar day of a due date, in the course's (Berkeley) time zone. */
export function dueDay(due) {
  if (!due) return null;
  const text = String(due);
  if (/^\d{4}-\d{2}-\d{2}$/.test(text)) return text;
  const parsed = new Date(text);
  if (Number.isNaN(parsed.getTime())) {
    const dateOnly = /\d{4}-\d{2}-\d{2}/.exec(text);
    return dateOnly ? dateOnly[0] : null;
  }
  return new Intl.DateTimeFormat('en-CA', {
    timeZone: 'America/Los_Angeles', year: 'numeric', month: '2-digit', day: '2-digit',
  }).format(parsed);
}

function sourceIds(assignment) {
  const ids = Array.isArray(assignment.source_ids) && assignment.source_ids.length
    ? assignment.source_ids
    : [assignment.id];
  return ids.map(String);
}

function mergeResources(...lists) {
  const seen = new Set();
  const merged = [];
  for (const resource of lists.flat()) {
    if (!resource?.link || seen.has(resource.link)) continue;
    seen.add(resource.link);
    merged.push(resource);
  }
  return merged.slice(0, 20);
}

/** Which Gradescope items (all sharing the website item's key) a website item stands for. */
function matchingGradescope(websiteItem, candidates) {
  if (!candidates.length) return [];
  const websiteDay = dueDay(websiteItem.due);
  const sameDay = websiteDay ? candidates.filter(item => dueDay(item.due) === websiteDay) : [];
  if (sameDay.length) return sameDay;
  if (candidates.length === 1) return candidates; // Gradescope's date wins
  const days = new Set(candidates.map(item => dueDay(item.due)));
  return days.size === 1 ? candidates : []; // versions with one shared deadline
}

/** Returns combined items, each with `source_ids` listing the source assignments it stands for. */
export function combineSourceAssignments(gradescopeAssignments = [], websiteAssignments = []) {
  const gradescope = gradescopeAssignments.map(item => ({ ...item, source: item.source || 'gradescope' }));
  const byKey = new Map();
  for (const item of gradescope) {
    const key = assignmentKey(item.title);
    if (!key) continue;
    if (!byKey.has(key)) byKey.set(key, []);
    byKey.get(key).push(item);
  }

  // Gradescope item id -> the combined item that now represents it.
  const representedBy = new Map();
  const combinedFrom = new Map(); // combined item -> the source items it stands for
  const results = [];
  const websiteOnly = [];

  for (const websiteItem of websiteAssignments) {
    const key = assignmentKey(websiteItem.title);
    let matches = key ? matchingGradescope(websiteItem, byKey.get(key) || []) : [];
    if (!matches.length) {
      const byTopic = gradescope.filter(item => topicMatches(item, websiteItem));
      if (byTopic.length === 1) matches = byTopic;
    }
    if (!matches.length) {
      websiteOnly.push(websiteItem);
      continue;
    }
    const existing = representedBy.get(String(matches[0].id));
    if (existing && matches.every(item => representedBy.get(String(item.id)) === existing)) {
      // Another website mention of an item already combined (for example an extension note).
      existing.source_ids = [...new Set([...existing.source_ids, ...sourceIds(websiteItem)])];
      existing.resources = mergeResources(existing.resources || [], websiteItem.resources || []);
      combinedFrom.get(existing).website.push(websiteItem);
      continue;
    }
    const primary = matches[0];
    const combined = matches.length === 1
      ? { ...primary }
      : {
        ...primary,
        // One deadline standing for every version: named like the website's generic item.
        title: websiteItem.title,
        combined_titles: matches.map(item => item.title),
      };
    combined.source = 'gradescope';
    combined.source_ids = [...new Set([...matches.flatMap(sourceIds), ...sourceIds(websiteItem)])];
    combined.resources = mergeResources(
      ...matches.map(item => item.resources || []),
      websiteItem.resources || [],
    );
    for (const item of matches) representedBy.set(String(item.id), combined);
    combinedFrom.set(combined, { gradescope: matches, website: [websiteItem] });
    results.push(combined);
  }

  // When the sources disagree on the date, the instructor chooses: the item lists
  // every version and has no date until one is set.
  for (const combined of results) {
    const { gradescope: fromGradescope, website } = combinedFrom.get(combined);
    const versions = [...fromGradescope, ...website].map(item => ({
      assignment_name: item.title,
      due: item.due || null,
      source: item.source || 'gradescope',
      html_url: item.html_url || '',
      resources: Array.isArray(item.resources) ? item.resources : [],
    }));
    // Every combined item lists what it was made from, so nothing is hidden.
    combined.merged_versions = versions;
    const days = new Set(versions.map(version => dueDay(version.due)).filter(Boolean));
    if (days.size > 1) {
      combined.due = null;
      combined.review_reasons = [DIFFERENT_DAYS_NOTE];
    }
  }

  // Gradescope items not combined with a website item, in Gradescope's order.
  const emitted = new Set(results);
  const ordered = [];
  for (const item of gradescope) {
    const combined = representedBy.get(String(item.id));
    if (combined) {
      if (emitted.has(combined)) {
        ordered.push(combined);
        emitted.delete(combined);
      }
    } else {
      ordered.push({ ...item, source_ids: sourceIds(item) });
    }
  }
  return [...ordered, ...websiteOnly];
}

/** Map of website item id -> ids of existing Gradescope items that already cover it. */
export function websiteItemsCoveredByGradescope(existing, websiteAssignments) {
  const gradescope = existing
    .filter(item => (item.source || 'gradescope') === 'gradescope')
    .map(item => ({ id: item.assignment_id, title: item.assignment_name, due: item.due }));
  if (!gradescope.length) return new Map();
  const gradescopeIds = new Set(gradescope.map(item => String(item.id)));
  const websiteIds = new Set(websiteAssignments.map(item => String(item.id)));
  const combined = combineSourceAssignments(gradescope, websiteAssignments);
  const covered = new Map();
  for (const item of combined) {
    // A disagreeing website date is not covered, so the instructor sees both dates.
    if (item.source !== 'gradescope' || (item.review_reasons || []).length) continue;
    const ids = (item.source_ids || []).map(String);
    const coveringIds = ids.filter(id => gradescopeIds.has(id));
    for (const id of ids) if (websiteIds.has(id)) covered.set(id, coveringIds);
  }
  return covered;
}

/** A stored item as one version of itself (the shape used in `merged_versions`). */
function storedVersion(item) {
  return {
    assignment_name: item.assignment_name,
    due: item.due || null,
    source: item.source || 'gradescope',
    html_url: item.html_url || '',
    resources: Array.isArray(item.resources) ? item.resources : [],
  };
}

/** Fields to add the website as a source of a stored item, or null if not applicable. */
export function withWebsiteSource(stored, websiteVersions, websiteIds = []) {
  const versions = Array.isArray(stored.merged_versions) && stored.merged_versions.length
    ? stored.merged_versions
    : [storedVersion(stored)];
  if (versions.some(version => version.source === 'website')) return null;
  const storedDay = dueDay(stored.due);
  const agreeing = websiteVersions.filter(version => (
    version.source === 'website' && (!version.due || !storedDay || dueDay(version.due) === storedDay)
  ));
  if (!agreeing.length) return null;
  const ids = Array.isArray(stored.source_ids) && stored.source_ids.length
    ? stored.source_ids.map(String)
    : [String(stored.assignment_id)];
  return {
    merged_versions: [...versions, ...agreeing],
    source_ids: [...new Set([...ids, ...websiteIds.map(String)])],
    resources: mergeResources(stored.resources || [], ...agreeing.map(version => version.resources || [])),
  };
}

export const DIFFERENT_DAYS_NOTE = 'Versions are due on different days. Use Edit to choose the due date.';

const keyOf = title => assignmentKey(title) || String(title || '').trim().toLowerCase();

/** "lab 2" -> "Lab 2"; "mini-midterm 1" -> "Mini-Midterm 1". */
function displayName(key) {
  return key.replace(/(^|[\s-])([a-z])/g, (_, before, letter) => before + letter.toUpperCase());
}

/** The versions an item stands for: its own merged versions, or itself. */
function versionsOf(item) {
  if (Array.isArray(item.merged_versions) && item.merged_versions.length) return item.merged_versions;
  return [{
    assignment_name: item.assignment_name,
    due: item.due || null,
    source: item.source || 'gradescope',
    html_url: item.html_url || '',
  }];
}

/** The due date all dated versions share (preferring Gradescope's time), or null if they disagree. */
function sharedDue(versions) {
  const dated = versions.filter(version => dueDay(version.due));
  if (!dated.length || new Set(dated.map(version => dueDay(version.due))).size > 1) return null;
  return (dated.find(version => (version.source || 'gradescope') === 'gradescope') || dated[0]).due;
}

/**
 * Merges review items sharing a kind and number ("Lab 2: Code", "Lab 2: Conceptual") into "Lab 2".
 * Keeps the best member's ID (Gradescope, then in-term dated, then first); `removedIds` are the rest.
 */
/**
 * Website items the course website itself lists as different deliverables: different
 * names due on different days ("Project 4 Artifact" 11/13, "Project 4 Peer Comments"
 * 11/20). They are not versions of one deadline, so they are not merged.
 */
function distinctWebsiteDeliverables(members) {
  if (members.length < 2 || members.some(({ item }) => (item.source || 'gradescope') !== 'website')) return false;
  const names = members.map(({ item }) => String(item.assignment_name || '').trim().toLowerCase());
  const days = members.map(({ item }) => dueDay(item.due));
  return new Set(names).size === names.length && days.every(Boolean) && new Set(days).size === days.length;
}

export function mergeDuplicateReviewItems(items, isOutsideTerm = () => false) {
  const groups = new Map();
  items.forEach((item, index) => {
    const key = keyOf(item.assignment_name);
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push({ item, index });
  });
  for (const [key, members] of [...groups]) {
    if (distinctWebsiteDeliverables(members)) groups.delete(key);
  }

  const merged = new Map(); // id of main item -> merged item
  const removedIds = [];
  const score = ({ item, index }) => [
    (item.source || 'gradescope') === 'gradescope' ? 0 : 1,
    item.due ? 0 : 1,
    item.due && isOutsideTerm(item.due) ? 1 : 0,
    index,
  ];
  const better = (a, b) => {
    const [x, y] = [score(a), score(b)];
    for (let i = 0; i < x.length; i += 1) if (x[i] !== y[i]) return x[i] < y[i];
    return false;
  };
  for (const [key, members] of groups) {
    if (members.length < 2) continue;
    const main = members.reduce((best, member) => (better(member, best) ? member : best)).item;
    const versions = members.flatMap(({ item }) => versionsOf(item));
    const due = sharedDue(versions);
    const days = [...new Set(versions.map(version => dueDay(version.due)).filter(Boolean))].sort();
    const reasons = [];
    if (days.length > 1) {
      reasons.push(DIFFERENT_DAYS_NOTE);
    }
    const { combined_titles: _titles, ...rest } = main;
    merged.set(String(main.assignment_id), {
      ...rest,
      assignment_name: assignmentKey(main.assignment_name) ? displayName(key) : main.assignment_name,
      due: due || null,
      resources: mergeResources(...members.map(({ item }) => item.resources || [])),
      source_ids: [...new Set(members.flatMap(({ item }) => (
        Array.isArray(item.source_ids) && item.source_ids.length ? item.source_ids : [item.assignment_id]
      ).map(String)))],
      merged_versions: versions,
      review_reasons: reasons,
    });
    for (const { item } of members) {
      if (item !== main) removedIds.push(String(item.assignment_id));
    }
  }
  const removed = new Set(removedIds);
  return {
    items: items
      .filter(item => !removed.has(String(item.assignment_id)))
      .map(item => merged.get(String(item.assignment_id)) || item),
    mergedIds: [...merged.keys()],
    removedIds,
  };
}

/** Notes for review items named like an already-published assignment. */
export function publishedNameReasons(items, published = []) {
  const titlesByKey = new Map();
  for (const item of published) {
    const key = keyOf(item.assignment_name);
    if (!titlesByKey.has(key)) titlesByKey.set(key, []);
    titlesByKey.get(key).push(item.assignment_name);
  }
  const reasons = new Map();
  for (const item of items) {
    const titles = [...new Set(titlesByKey.get(keyOf(item.assignment_name)) || [])];
    if (!titles.length) continue;
    const quoted = titles.slice(0, 3).map(title => `“${title}”`).join(', ');
    reasons.set(String(item.assignment_id), [`Same name as ${quoted}${titles.length > 3 ? ', …' : ''}, already in this course`]);
  }
  return reasons;
}

const SEASON_CODES = { fa: 'Fall', sp: 'Spring', su: 'Summer', wi: 'Winter' };

/** Loose date range for a term ("Fall 2026" or a "/fa26/" URL), or null if unknown. */
export function termDateRange(term, websiteUrl = '') {
  let text = String(term || '');
  let year = Number(/\b(19|20)\d{2}\b/.exec(text)?.[0]) || null;
  if (!year) {
    const fromUrl = /(?:^|\/)(fa|sp|su|wi)(\d{2})(?:\/|$)/i.exec(String(websiteUrl || '').replace(/^https?:\/\/[^/]+/i, ''));
    if (fromUrl) {
      year = 2000 + Number(fromUrl[2]);
      text = `${SEASON_CODES[fromUrl[1].toLowerCase()]} ${year}`;
    }
  }
  if (!year) return null;
  const pad = n => String(n).padStart(2, '0');
  const day = (y, m, d) => `${y}-${pad(m)}-${pad(d)}`;
  if (/\b(fall|autumn)\b/i.test(text)) return [day(year, 7, 15), day(year + 1, 1, 31)];
  if (/\bspring\b/i.test(text)) return [day(year - 1, 12, 15), day(year, 6, 15)];
  if (/\bsummer\b/i.test(text)) return [day(year, 5, 1), day(year, 9, 15)];
  if (/\bwinter\b/i.test(text)) return [day(year - 1, 11, 15), day(year, 3, 31)];
  return [day(year, 1, 1), day(year + 1, 1, 31)];
}

/** Returns a check for whether a due date falls outside the term. */
export function outsideTermChecker(term, websiteUrl = '') {
  const range = termDateRange(term, websiteUrl);
  return due => {
    const day = dueDay(due);
    return Boolean(range && day && (day < range[0] || day > range[1]));
  };
}
