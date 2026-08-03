import { useEffect, useState } from "react";

/**
 * Ticking clock for countdowns.
 *
 * Countdowns are rendered from `remaining_sec` plus elapsed local time instead of
 * being pushed once per second by the server, which keeps the event stream quiet.
 * The interval pauses while the tab is hidden so a backgrounded phone stays idle.
 */
export function useNow(intervalMs = 1_000, enabled = true) {
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    if (!enabled) return;
    let timer: number | null = null;

    const start = () => {
      if (timer !== null) return;
      timer = window.setInterval(() => setNow(Date.now()), intervalMs);
    };
    const stop = () => {
      if (timer === null) return;
      window.clearInterval(timer);
      timer = null;
    };
    const onVisibility = () => {
      setNow(Date.now());
      if (document.visibilityState === "visible") start();
      else stop();
    };

    if (document.visibilityState === "visible") start();
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      document.removeEventListener("visibilitychange", onVisibility);
      stop();
    };
  }, [enabled, intervalMs]);

  return now;
}
