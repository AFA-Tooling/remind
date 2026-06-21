// Pure group-assignment helpers (no I/O) so randomization is unit-testable.
//
// Balance-aware assignment: given the emails still needing a group and the current
// size of each group, shuffle the newcomers and hand each to whichever group is
// currently smaller (ties broken randomly). This keeps Group 1 and Group 2 within
// one of each other whether we assign the whole cohort at once or a late consenter
// one at a time.

/** Fisher–Yates shuffle (returns a new array). rng() should yield [0,1). */
export function shuffle(arr, rng = Math.random) {
  const a = arr.slice();
  for (let i = a.length - 1; i > 0; i--) {
    const j = Math.floor(rng() * (i + 1));
    [a[i], a[j]] = [a[j], a[i]];
  }
  return a;
}

/**
 * Assign each email to group 1 or 2, keeping the groups balanced.
 * @param {string[]} emails  emails needing assignment (currently group=null)
 * @param {number} count1    existing Group 1 size
 * @param {number} count2    existing Group 2 size
 * @param {() => number} rng
 * @returns {Array<{ email: string, group: 1|2 }>}
 */
export function assignBalanced(emails, count1 = 0, count2 = 0, rng = Math.random) {
  let c1 = count1;
  let c2 = count2;
  const out = [];
  for (const email of shuffle(emails, rng)) {
    let group;
    if (c1 < c2) group = 1;
    else if (c2 < c1) group = 2;
    else group = rng() < 0.5 ? 1 : 2; // tie → coin flip
    if (group === 1) c1++; else c2++;
    out.push({ email, group });
  }
  return out;
}
