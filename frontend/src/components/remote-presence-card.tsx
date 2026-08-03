import { Activity, Globe2, Laptop, Loader2, Radio, Smartphone, Square } from "lucide-react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useAsyncAction } from "@/hooks/use-async-action";
import { useService } from "@/hooks/use-service";
import { api } from "@/lib/api";
import type { RemoteClient } from "@/lib/types";
import { cn } from "@/lib/utils";

function DeviceIcon({ device }: { device: string }) {
  const lower = device.toLowerCase();
  if (lower.includes("iphone") || lower.includes("android") || lower.includes("ipad")) {
    return <Smartphone className="size-4" />;
  }
  return <Laptop className="size-4" />;
}

function formatRtt(ms: number | null | undefined) {
  if (ms == null || Number.isNaN(ms)) return "—";
  if (ms < 10) return `${ms.toFixed(1)} ms`;
  return `${Math.round(ms)} ms`;
}

function rttTone(ms: number | null | undefined) {
  if (ms == null) return "text-muted-foreground";
  if (ms < 80) return "text-foreground";
  if (ms < 180) return "text-muted-foreground";
  return "text-destructive";
}

function tabLabel(tab: string | null) {
  if (!tab) return null;
  const labels: Record<string, string> = {
    devices: "Devices",
    sessions: "Running",
    discover: "Connect",
    settings: "Settings",
  };
  return labels[tab] ?? tab;
}

function RemoteRow({
  remote,
  rttMs,
}: {
  remote: RemoteClient;
  rttMs: number | null;
}) {
  const location = [remote.country, remote.ip].filter(Boolean).join(" · ");
  const doing =
    remote.activity ||
    (tabLabel(remote.tab) ? `On ${tabLabel(remote.tab)}` : "Connected");

  return (
    <div className="border-hairline flex flex-col gap-3 rounded-2xl border px-3.5 py-3 transition-[border-color,background-color] duration-300">
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 items-center gap-2.5">
          <span className="bg-secondary text-foreground grid size-9 place-items-center rounded-xl">
            <DeviceIcon device={remote.device} />
          </span>
          <div className="min-w-0">
            <p className="truncate text-sm font-medium tracking-tight">
              {remote.device}
              <span className="text-muted-foreground font-normal"> · {remote.browser}</span>
            </p>
            <p className="text-muted-foreground truncate text-xs">
              {location || "IP pending"}
            </p>
          </div>
        </div>
        <Badge variant={remote.online ? "success" : "warning"}>
          {remote.online ? "Online" : "Away"}
        </Badge>
      </div>

      <div className="grid grid-cols-2 gap-2 text-xs sm:grid-cols-3">
        <div className="bg-elevated rounded-xl px-3 py-2">
          <p className="text-muted-foreground">Round-trip</p>
          <p className={cn("mt-0.5 font-mono text-sm tabular-nums", rttTone(rttMs))}>
            {formatRtt(rttMs)}
          </p>
        </div>
        <div className="bg-elevated rounded-xl px-3 py-2">
          <p className="text-muted-foreground">Activity</p>
          <p className="mt-0.5 truncate font-medium">{doing}</p>
        </div>
        <div className="bg-elevated col-span-2 rounded-xl px-3 py-2 sm:col-span-1">
          <p className="text-muted-foreground">Idle</p>
          <p className="mt-0.5 font-mono tabular-nums">
            {remote.idle_for_sec < 2 ? "now" : `${Math.round(remote.idle_for_sec)}s`}
          </p>
        </div>
      </div>
    </div>
  );
}

/**
 * Host-only monitor: who is driving toys over the Cloudflare tunnel, and the real
 * browser↔browser latency of that control path.
 */
export function RemotePresenceCard({ compact = false }: { compact?: boolean }) {
  const { state, role, rttByPeer, refresh } = useService();
  const [stopAll, stopping] = useAsyncAction(() => api.command.stopAll(), {
    success: "Everything stopped",
    errorTitle: "Stop failed",
    onDone: () => void refresh(),
  });

  if (role !== "host") return null;

  const remotes = state?.presence?.remotes ?? [];
  const tunnelOn = Boolean(state?.tunnel?.running || state?.tunnel?.desired);
  // On Devices, stay quiet until the tunnel is relevant; Settings always shows the card.
  if (compact && remotes.length === 0 && !tunnelOn) return null;

  return (
    <Card className={cn(compact && "shadow-none")}>
      <CardHeader className="gap-1">
        <div className="flex items-center gap-2">
          <Radio className="size-4" />
          <CardTitle className="text-base">Remote control</CardTitle>
          {remotes.length > 0 ? (
            <Badge variant="default" className="ml-auto">
              {remotes.length} online
            </Badge>
          ) : null}
        </div>
        <CardDescription>
          People connected through the public tunnel. Round-trip is measured browser to
          browser — not a network ping to Cloudflare.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {!tunnelOn && remotes.length === 0 ? (
          <Alert variant="info">
            <Globe2 />
            <AlertTitle>Tunnel is off</AlertTitle>
            <AlertDescription>
              Start the Cloudflare tunnel in Settings so someone outside your network can
              open the panel (they’ll need the console access code).
            </AlertDescription>
          </Alert>
        ) : null}

        {tunnelOn && remotes.length === 0 ? (
          <div className="text-muted-foreground flex items-center gap-2 rounded-2xl border border-dashed px-3 py-4 text-sm">
            <Activity className="size-4 shrink-0" />
            Waiting for a remote browser… Share the tunnel URL; they’ll enter the code
            printed in this machine’s console.
          </div>
        ) : null}

        {remotes.map((remote) => (
          <RemoteRow
            key={remote.client_id}
            remote={remote}
            rttMs={rttByPeer[remote.client_id] ?? remote.rtt_ms}
          />
        ))}

        {remotes.length > 0 ? (
          <Button
            variant="destructive"
            className="w-full"
            disabled={stopping}
            onClick={() => void stopAll()}
          >
            {stopping ? <Loader2 className="animate-spin" /> : <Square />}
            Stop all toys now
          </Button>
        ) : null}
      </CardContent>
    </Card>
  );
}
