// User-facing study-gating messages, kept in one place so the API and any client
// that surfaces them stay consistent.

export const LOCKOUT_MESSAGE =
  "The window to consent to the AutoRemind research study has closed. " +
  "If access opens up in the future, we'll reach out to your registered email.";

export const WAITLIST_MESSAGE =
  "You’re on the waitlist. Your preferences have been saved. As part of this study, " +
  "participants are randomly assigned to receive AutoRemind notifications either at the " +
  "start of the semester or at another time. You’ll receive an email when your access " +
  "is activated. Thank you!";
