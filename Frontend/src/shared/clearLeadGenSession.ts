import { stopLeadGenPolling } from './leadGenPoller';

/**
 * Clears AI Lead Gen UI state stored in the browser. Call on logout or session expiry so
 * the next user (or same user after re-login) never sees another account's chat.
 */
export function clearLeadGenSessionOnAuthEnd(): void {
  try {
    stopLeadGenPolling();
  } catch {
    /* ignore */
  }
  try {
    sessionStorage.removeItem('leadGenerationChatState');
    sessionStorage.removeItem('preselectedLeadIds');
  } catch {
    /* ignore */
  }
  try {
    localStorage.removeItem('ai_lead_gen_discarded');
  } catch {
    /* ignore */
  }
  try {
    window.dispatchEvent(new CustomEvent('leadGenCancelled'));
  } catch {
    /* ignore */
  }
}
