import { CloudOff, RadioTower, RefreshCw, Wifi } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import type { LinkStatus } from "@/lib/types";

const LABELS: Record<LinkStatus, { text: string; hint: string }> = {
  live: { text: "Live", hint: "Streaming updates from the service" },
  polling: { text: "Polling", hint: "Live stream unavailable — refreshing on a timer" },
  connecting: { text: "Connecting", hint: "Opening the live connection" },
  offline: { text: "Offline", hint: "The service is unreachable — retrying automatically" },
};

export function LinkBadge({ status }: { status: LinkStatus }) {
  const { text, hint } = LABELS[status];
  const variant =
    status === "live" ? "success" : status === "offline" ? "destructive" : "warning";
  const Icon =
    status === "live"
      ? Wifi
      : status === "polling"
        ? RefreshCw
        : status === "connecting"
          ? RadioTower
          : CloudOff;

  return (
    <Badge variant={variant} title={hint} className="gap-1.5 px-2.5 py-1">
      <Icon
        className={
          status === "connecting"
            ? "animate-spin"
            : status === "live"
              ? "animate-pulse-soft"
              : undefined
        }
        aria-hidden
      />
      <span className="hidden sm:inline">{text}</span>
      <span className="sr-only">{hint}</span>
    </Badge>
  );
}
