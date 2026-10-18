const STORAGE_KEY = 'leadGenerationChatState';
const DISCARDED_FLAG_KEY = 'ai_lead_gen_discarded';

const POLL_INTERVAL_MS = 10 * 1000;   // 10 seconds per poll
// 6 minutes: Overture cold-loads (a brand-new area/category) can take 1–several
// minutes to fetch from S3 and fill the log. Warm/Google searches still resolve on
// the first poll, so this longer ceiling only matters while a cold area is loading.
const POLL_TIMEOUT_MS = 6 * 60 * 1000;

declare global {
  interface Window {
    __leadGenPoller?: number | null;
    __leadGenPollingLogId?: string | null;
    __leadGenPollingStartedAt?: number | null;
    /** Set for the active poll so merged sessionStorage is tagged to the correct user */
    __leadGenPollOwnerUserId?: string | null;
  }
}

export function startLeadGenPolling(logId: string, apiService: any, ownerUserId?: string | null) {
  // avoid duplicates for same log
  if (window.__leadGenPoller && window.__leadGenPollingLogId === logId) return;

  // stop old poller (if any)
  if (window.__leadGenPoller) {
    clearInterval(window.__leadGenPoller);
    window.__leadGenPoller = null;
  }

  window.__leadGenPollingLogId = logId;
  window.__leadGenPollingStartedAt = Date.now();
  window.__leadGenPollOwnerUserId = ownerUserId ?? null;

  // Notify that lead generation has started
  window.dispatchEvent(new CustomEvent('leadGenStarted', { detail: { logId } }));

  const stopPoller = () => {
    if (window.__leadGenPoller) {
      clearInterval(window.__leadGenPoller);
      window.__leadGenPoller = null;
    }
    window.__leadGenPollingLogId = null;
    window.__leadGenPollingStartedAt = null;
  };

  const poll = async () => {
    // Stop after 1 minute and notify UI to show N/A
    const elapsed = Date.now() - (window.__leadGenPollingStartedAt ?? 0);
    if (elapsed >= POLL_TIMEOUT_MS) {
      stopPoller();
      window.dispatchEvent(new CustomEvent('leadGenPollingTimeout', { detail: { logId } }));
      return;
    }

    // stop if discarded
    const discardedFlag = localStorage.getItem(DISCARDED_FLAG_KEY);
    if (discardedFlag) {
      try {
        const flag = JSON.parse(discardedFlag);
        const flagAge = Date.now() - (flag.timestamp || 0);
        // If discarded flag is recent (within 10 seconds), stop polling
        if (flagAge < 10000) {
          stopPoller();
          return;
        }
      } catch (e) {
        // Invalid flag, ignore
      }
    }

    try {
      const res = await apiService.getLeadLogById(logId);

      // Logout / stopLeadGenPolling clears the interval — do not write another user's session
      if (!window.__leadGenPoller) {
        return;
      }

      if (res?.error) return;

      const leads = res?.data?.leads || [];
      const logStatus = (res?.data as any)?.status;

      // Cold-load finished with no results (or crashed) → stop polling and tell the UI to
      // clear its "generating" banner/loader, instead of spinning until POLL_TIMEOUT_MS.
      if (leads.length === 0 && (logStatus === 'empty' || logStatus === 'failed')) {
        stopPoller();
        window.dispatchEvent(new CustomEvent('leadGenCancelled'));
        return;
      }

      if (leads.length > 0) {
        const chatTitle = res?.data?.chat_title || null;
        // merge into existing saved state (keep messages/prompt etc)
        const prev = (() => {
          try {
            return JSON.parse(sessionStorage.getItem(STORAGE_KEY) || '{}');
          } catch {
            return {};
          }
        })();

        const ownerId = window.__leadGenPollOwnerUserId;
        if (ownerId && prev.userId && prev.userId !== ownerId) {
          return;
        }

        // Check if state was discarded or logId mismatch
        if (prev.discarded === true) {
          return;
        }
        if (prev.currentLogId && prev.currentLogId !== logId) {
          return;
        }

        const next = {
          ...prev,
          currentLogId: logId,
          currentLeads: leads,
          resultsTitle: chatTitle ?? prev.resultsTitle ?? null,
          isLoadingLeads: false,
          showFullPageLoader: false,
          timestamp: Date.now(),
          ...(ownerId ? { userId: ownerId } : {}),
        };

        sessionStorage.setItem(STORAGE_KEY, JSON.stringify(next));

        // notify UI (works even if user returns later)
        window.dispatchEvent(
          new CustomEvent('leadGenLeadsReady', { detail: { logId, leads, chatTitle } })
        );

        // stop poller
        stopPoller();
      }
    } catch {
      // ignore temporary network errors
    }
  };

  window.__leadGenPoller = window.setInterval(poll, POLL_INTERVAL_MS);
  poll(); // immediate poll
}

export function stopLeadGenPolling() {
  if (window.__leadGenPoller) {
    clearInterval(window.__leadGenPoller);
    window.__leadGenPoller = null;
  }
  window.__leadGenPollingLogId = null;
  window.__leadGenPollingStartedAt = null;
  window.__leadGenPollOwnerUserId = null;
}

