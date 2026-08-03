import { useCallback, useRef, useState } from "react";
import { toast } from "sonner";

interface Options {
  /** Toast shown on success; omit for silent success. */
  success?: string;
  /** Title of the error toast. */
  errorTitle?: string;
  /** Runs after success or failure (e.g. refresh the snapshot). */
  onDone?: () => void;
}

/**
 * Runs one async action at a time and reports failures as toasts.
 *
 * The re-entrancy guard matters on touch devices, where a tap can fire twice (ghost
 * click, impatient double tap) and a duplicated "connect" or "scan" would queue a
 * second BLE operation behind the first.
 */
export function useAsyncAction<Args extends unknown[]>(
  action: (...args: Args) => Promise<unknown>,
  options: Options = {},
) {
  const [pending, setPending] = useState(false);
  const runningRef = useRef(false);
  const optionsRef = useRef(options);
  optionsRef.current = options;
  const actionRef = useRef(action);
  actionRef.current = action;

  const run = useCallback(async (...args: Args) => {
    if (runningRef.current) return false;
    runningRef.current = true;
    setPending(true);
    try {
      await actionRef.current(...args);
      const { success } = optionsRef.current;
      if (success) toast.success(success);
      return true;
    } catch (cause) {
      toast.error(optionsRef.current.errorTitle ?? "Action failed", {
        description: cause instanceof Error ? cause.message : "Unknown error",
      });
      return false;
    } finally {
      runningRef.current = false;
      setPending(false);
      optionsRef.current.onDone?.();
    }
  }, []);

  return [run, pending] as const;
}
