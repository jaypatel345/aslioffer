const STORAGE_KEY = 'aslioffer:case-tokens';

type TokenMap = Record<string, { token: string; expiresAt: string }>;

const readAll = (): TokenMap => {
  try {
    const parsed = JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}');
    return parsed && typeof parsed === 'object' ? parsed : {};
  } catch {
    return {};
  }
};

// Kept in memory too, so a case opened in this tab still works when storage is blocked.
let cache: TokenMap = readAll();

const persist = () => {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(cache));
  } catch {
    /* private browsing: in-memory only */
  }
};

/**
 * Per-case access tokens. The backend returns a token once at upload; without it
 * the case cannot be read (it answers 404). Tokens live only in this browser, so
 * a case is visible on the device that uploaded it.
 */
export const caseAccess = {
  get(offerId: number): string | null {
    const entry = cache[String(offerId)];
    if (!entry) return null;
    if (new Date(entry.expiresAt).getTime() < Date.now()) {
      this.forget(offerId);
      return null;
    }
    return entry.token;
  },

  set(offerId: number, token: string, expiresAt: string) {
    cache = { ...cache, [String(offerId)]: { token, expiresAt } };
    persist();
  },

  forget(offerId: number) {
    const next = { ...cache };
    delete next[String(offerId)];
    cache = next;
    persist();
  },
};
