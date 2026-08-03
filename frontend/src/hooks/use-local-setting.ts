import { useCallback, useSyncExternalStore } from "react";

type Value = string | number | boolean;

/**
 * Small persisted UI preference, shared by every component that reads the same key.
 *
 * The value lives in a module-level store instead of component state so that a toggle
 * in Settings and the switch it controls elsewhere never disagree. `localStorage` access
 * is wrapped because Safari throws in private mode, where the preference simply lasts
 * for the session.
 */
const cache = new Map<string, Value>();
const listeners = new Map<string, Set<() => void>>();

function storageKey(key: string) {
  return `lovensepy.${key}`;
}

function read<T extends Value>(key: string, fallback: T): T {
  if (cache.has(key)) return cache.get(key) as T;
  let value = fallback;
  try {
    const raw = window.localStorage.getItem(storageKey(key));
    if (raw !== null) value = JSON.parse(raw) as T;
  } catch {
    // Denied or corrupt: fall back to the default.
  }
  cache.set(key, value);
  return value;
}

export function useLocalSetting<T extends Value>(key: string, fallback: T) {
  const subscribe = useCallback(
    (listener: () => void) => {
      const set = listeners.get(key) ?? new Set();
      listeners.set(key, set);
      set.add(listener);
      return () => set.delete(listener);
    },
    [key],
  );

  const value = useSyncExternalStore(
    subscribe,
    () => read(key, fallback),
    () => fallback,
  );

  const update = useCallback(
    (next: T) => {
      cache.set(key, next);
      try {
        window.localStorage.setItem(storageKey(key), JSON.stringify(next));
      } catch {
        // Keep the in-memory value; persistence is best effort.
      }
      for (const listener of listeners.get(key) ?? []) listener();
    },
    [key],
  );

  return [value, update] as const;
}
