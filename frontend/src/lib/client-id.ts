const STORAGE_KEY = "lovensepy.client_id";

/** Stable id for this browser tab — ties REST activity to the live /ws presence row. */
export function getClientId(): string {
  try {
    const existing = window.sessionStorage.getItem(STORAGE_KEY);
    if (existing) return existing;
    const next =
      typeof crypto !== "undefined" && "randomUUID" in crypto
        ? crypto.randomUUID()
        : `c_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 10)}`;
    window.sessionStorage.setItem(STORAGE_KEY, next);
    return next;
  } catch {
    return `c_${Date.now().toString(36)}`;
  }
}
