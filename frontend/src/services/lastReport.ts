const STORAGE_KEY = 'aslioffer:last-report-id';

const read = (): number | null => {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    const id = Number(raw);
    return raw && Number.isFinite(id) ? id : null;
  } catch {
    // Private browsing / blocked storage — the nav simply stays hidden.
    return null;
  }
};

// useSyncExternalStore needs a cached snapshot, not a fresh read per call.
let snapshot: number | null = read();
const listeners = new Set<() => void>();

/**
 * The offer whose investigation most recently completed on this device.
 * Null until the user actually runs the agent pipeline, which is what gates
 * the "Report" link in the navbar.
 */
export const lastReport = {
  get: (): number | null => snapshot,

  set(offerId: number) {
    snapshot = offerId;
    try {
      localStorage.setItem(STORAGE_KEY, String(offerId));
    } catch {
      // Keep the in-memory value for this session even if persisting fails.
    }
    listeners.forEach((notify) => notify());
  },

  subscribe(listener: () => void) {
    listeners.add(listener);
    return () => {
      listeners.delete(listener);
    };
  },
};
