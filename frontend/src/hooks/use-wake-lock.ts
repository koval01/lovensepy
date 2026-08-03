import { useCallback, useEffect, useRef, useState } from "react";

type WakeLockSentinelLike = { release: () => Promise<void>; released: boolean };
type WakeLockCapableNavigator = Navigator & {
  wakeLock?: { request: (type: "screen") => Promise<WakeLockSentinelLike> };
};

/** Absent in Firefox and older Safari; the UI hides the toggle instead of lying. */
export const wakeLockSupported = typeof navigator !== "undefined" && "wakeLock" in navigator;

/**
 * Keeps the screen on while a session is running (Chrome/Edge/Android, Safari 16.4+).
 *
 * A phone that locks itself mid-session is not just annoying: on iOS the page is
 * suspended, so the live socket dies and the user loses the stop button. The API is
 * absent in Firefox, so this degrades to a no-op and the UI hides the toggle.
 */
export function useWakeLock(enabled: boolean) {
  const supported = wakeLockSupported;
  const [active, setActive] = useState(false);
  const sentinelRef = useRef<WakeLockSentinelLike | null>(null);

  const release = useCallback(async () => {
    const sentinel = sentinelRef.current;
    sentinelRef.current = null;
    setActive(false);
    if (sentinel && !sentinel.released) {
      try {
        await sentinel.release();
      } catch {
        // Already released by the browser (tab hidden, battery saver).
      }
    }
  }, []);

  const acquire = useCallback(async () => {
    if (!supported || sentinelRef.current) return;
    try {
      const sentinel = await (navigator as WakeLockCapableNavigator).wakeLock?.request("screen");
      if (!sentinel) return;
      sentinelRef.current = sentinel;
      setActive(true);
    } catch {
      setActive(false);
    }
  }, [supported]);

  useEffect(() => {
    if (!supported) return;
    if (enabled && document.visibilityState === "visible") void acquire();
    else void release();

    // The browser drops the lock whenever the page is hidden; re-take it on return.
    const onVisible = () => {
      if (!enabled) return;
      if (document.visibilityState === "visible") void acquire();
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      document.removeEventListener("visibilitychange", onVisible);
      void release();
    };
  }, [acquire, enabled, release, supported]);

  return { supported, active } as const;
}
