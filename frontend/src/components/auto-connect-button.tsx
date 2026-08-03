import { Loader2, Radar } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { useAsyncAction } from "@/hooks/use-async-action";
import { useService } from "@/hooks/use-service";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";

interface Props {
  size?: "default" | "sm" | "lg";
  variant?: "default" | "outline" | "secondary";
  className?: string;
  label?: string;
}

/**
 * The whole onboarding path in one tap: scan, connect everything that answers, and
 * reconnect toys that went away. Per-device failures are reported but never block the
 * others, which matters when a nearby toy is out of battery.
 */
export function AutoConnectButton({ size = "default", variant = "default", className, label }: Props) {
  const { state, refresh } = useService();
  const bleOn = state?.transports.ble ?? false;
  const scanTimeout = state?.ble?.scan.timeout_sec;

  const [run, pending] = useAsyncAction(
    async () => {
      const result = await api.ble.autoConnect({ timeout: scanTimeout, include_registered: true });
      const failures = result.results.filter((row) => !row.ok);
      if (result.connected.length) {
        toast.success(
          `Connected ${result.connected.length} device${result.connected.length === 1 ? "" : "s"}`,
          failures.length ? { description: `${failures.length} did not answer.` } : undefined,
        );
      } else if (result.scanned === 0) {
        toast.info("No devices found", {
          description: "Turn a toy on, keep it close, and try again.",
        });
      } else {
        toast.warning("Nothing could be connected", {
          description: failures[0]?.error ?? "The devices did not answer.",
        });
      }
    },
    { errorTitle: "Scan failed", onDone: () => void refresh(true) },
  );

  return (
    <Button
      size={size}
      variant={variant}
      className={cn(className)}
      disabled={!bleOn || pending}
      onClick={() => void run()}
      title={bleOn ? "Scan and connect nearby toys" : "Bluetooth is disabled in settings"}
    >
      {pending ? <Loader2 className="animate-spin" /> : <Radar />}
      {pending ? "Scanning…" : (label ?? "Find my toys")}
    </Button>
  );
}
