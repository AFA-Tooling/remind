// User-facing study-gating messages, kept in one place so the API and any client
// that surfaces them stay consistent.

export const LOCKOUT_MESSAGE =
  "The window to consent to the AutoRemind research study has closed. " +
  "If access opens up in the future, we'll reach out to your registered email.";

export const WAITLIST_MESSAGE =
  "Because this is AutoRemind's pilot semester, we have limited compute available. " +
  "For now we've placed you on the waitlist — your preferences have been saved, and " +
  "we'll email your registered address as soon as access opens up.";
