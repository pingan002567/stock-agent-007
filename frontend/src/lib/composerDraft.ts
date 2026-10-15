/** Unsent composer text is keyed by session. Empty id is the unsaved「新对话」draft. */
export const NEW_SESSION_DRAFT_KEY = "";

export function composerDraftKey(sessionId: string | null | undefined): string {
  return sessionId || NEW_SESSION_DRAFT_KEY;
}

/** Move the unsaved「新对话」draft onto a session just created from that composer. */
export function adoptNewSessionDraft(
  drafts: Record<string, string>,
  sessionId: string,
): Record<string, string> {
  const text = drafts[NEW_SESSION_DRAFT_KEY] ?? "";
  if (!text || drafts[sessionId]) return drafts;
  return { ...drafts, [NEW_SESSION_DRAFT_KEY]: "", [sessionId]: text };
}
