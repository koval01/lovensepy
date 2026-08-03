import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { api } from "@/lib/api";
import { featureLabel } from "@/lib/format";

/**
 * Minimum spacing between level writes for one motor.
 * Kept low: the scheduler updates an existing hold in place (one UART write),
 * so we no longer need a long gap to absorb cancel/stop/battery round-trips.
 */
const MIN_INTERVAL_MS = 45;
/** How long local input wins over server state after the last touch. */
const HOLD_MS = 1_400;

interface Options {
  toyId: string;
  feature: string;
  /** Level the service reports for this motor (0 when no session holds it). */
  serverLevel: number;
  onSettled?: () => void;
}

/**
 * Slider plumbing for one motor.
 *
 * Dragging a slider can emit dozens of events per second; each one is a Bluetooth
 * write or an HTTP call to the Lovense app, and firing them all makes toys stutter and
 * fall behind. So writes are coalesced: at most one request per motor is in flight,
 * only the newest value survives the wait, and the value at release is always sent
 * last. Meanwhile the knob follows the finger immediately and server state is ignored
 * briefly afterwards, otherwise an echo of an older level would yank it back.
 */
export function useLevelControl({ toyId, feature, serverLevel, onSettled }: Options) {
  const [level, setLevel] = useState(serverLevel);
  const [busy, setBusy] = useState(false);

  const pendingRef = useRef<number | null>(null);
  const inFlightRef = useRef(false);
  const timerRef = useRef<number | null>(null);
  const lastSentAtRef = useRef(0);
  const holdUntilRef = useRef(0);
  const pumpRef = useRef<(immediate?: boolean) => void>(() => {});
  const settledRef = useRef(onSettled);
  settledRef.current = onSettled;

  useEffect(() => {
    if (Date.now() < holdUntilRef.current) return;
    setLevel((current) => (current === serverLevel ? current : serverLevel));
  }, [serverLevel]);

  const write = useCallback(
    async (value: number) => {
      inFlightRef.current = true;
      setBusy(true);
      lastSentAtRef.current = Date.now();
      try {
        if (value <= 0) {
          if (feature === "All") await api.command.stopToy(toyId);
          else await api.command.stopFeature(toyId, feature, { timeoutMs: 8_000 });
        } else {
          await api.command.fn(
            { toy_id: toyId, actions: { [feature]: value }, time: 0 },
            { timeoutMs: 8_000 },
          );
        }
      } catch (cause) {
        pendingRef.current = null;
        holdUntilRef.current = 0;
        setLevel(serverLevel);
        toast.error(`${featureLabel(feature)} failed`, {
          description: cause instanceof Error ? cause.message : "Unknown error",
        });
      } finally {
        inFlightRef.current = false;
        setBusy(false);
        settledRef.current?.();
      }
    },
    [feature, serverLevel, toyId],
  );

  const pump = useCallback(
    (immediate = false) => {
      if (inFlightRef.current || timerRef.current !== null) return;
      if (pendingRef.current === null) return;
      const wait = immediate ? 0 : Math.max(0, MIN_INTERVAL_MS - (Date.now() - lastSentAtRef.current));
      timerRef.current = window.setTimeout(() => {
        timerRef.current = null;
        const value = pendingRef.current;
        if (value === null) return;
        pendingRef.current = null;
        void write(value).then(() => pumpRef.current());
      }, wait);
    },
    [write],
  );
  pumpRef.current = pump;

  /** Continuous updates while dragging. */
  const change = useCallback(
    (value: number) => {
      holdUntilRef.current = Date.now() + HOLD_MS;
      setLevel(value);
      pendingRef.current = value;
      pump();
    },
    [pump],
  );

  /** Release, or a discrete action (buttons, quick levels): send without waiting. */
  const commit = useCallback(
    (value: number) => {
      holdUntilRef.current = Date.now() + HOLD_MS;
      setLevel(value);
      pendingRef.current = value;
      if (timerRef.current !== null) {
        window.clearTimeout(timerRef.current);
        timerRef.current = null;
      }
      pump(true);
    },
    [pump],
  );

  useEffect(
    () => () => {
      if (timerRef.current !== null) window.clearTimeout(timerRef.current);
    },
    [],
  );

  return { level, busy, change, commit } as const;
}
