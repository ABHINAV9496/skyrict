/**
 * Cross-component conversation-list refresh.
 *
 * The AI conversation title is generated server-side in a background task a
 * moment after the agent reply is persisted, so the sidebar (and the open
 * conversation's header) would otherwise keep stale titles until the next
 * navigation. Components broadcast `notifyConversationListChanged()` after a
 * turn completes; panels rendering conversation metadata listen and refetch.
 */

/** Window event name broadcast whenever a conversation's list entry may have changed. */
export const CONVERSATION_LIST_CHANGED_EVENT = "skyrict:conversations-refresh";

/** Broadcast that conversation metadata may have changed (e.g. the AI title). */
export function notifyConversationListChanged(): void {
  window.dispatchEvent(new CustomEvent(CONVERSATION_LIST_CHANGED_EVENT));
}