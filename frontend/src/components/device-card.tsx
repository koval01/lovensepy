import {
  Battery,
  BatteryLow,
  Bluetooth,
  BluetoothOff,
  Cloud,
  Loader2,
  Plug,
  Signal,
  Square,
  Trash2,
} from "lucide-react";
import { useMemo } from "react";

import { DurationPicker } from "@/components/duration-picker";
import { FeatureSlider } from "@/components/feature-slider";
import { PatternDialog } from "@/components/pattern-dialog";
import { PulseDialog } from "@/components/pulse-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import { useAsyncAction } from "@/hooks/use-async-action";
import { useLocalSetting } from "@/hooks/use-local-setting";
import { useService } from "@/hooks/use-service";
import { api } from "@/lib/api";
import { controllableFeatures, featureRange, levelsFromTasks, modeSessionFor } from "@/lib/derive";
import { batteryTone, formatSeconds, presetLabel, signalBars, toyTypeLabel } from "@/lib/format";
import type { ToyView } from "@/lib/types";
import { cn, slotKey } from "@/lib/utils";

function SignalMeter({ rssi }: { rssi: number | null }) {
  const bars = signalBars(rssi);
  if (!rssi) return null;
  return (
    <span
      className="text-muted-foreground inline-flex items-center gap-1 text-xs"
      title={`${rssi} dBm`}
    >
      <Signal className={cn("size-3.5", bars <= 1 ? "text-muted-foreground" : "text-foreground")} />
      {bars}/4
    </span>
  );
}

export function DeviceCard({ toy }: { toy: ToyView }) {
  const { state, refresh, role } = useService();
  const canManageBle = role !== "remote";
  const tasks = state?.tasks ?? [];
  const levels = useMemo(() => levelsFromTasks(tasks), [tasks]);
  const features = useMemo(() => controllableFeatures(toy, state), [state, toy]);
  const session = modeSessionFor(tasks, toy.id);
  const [duration, setDuration] = useLocalSetting<number>("session-duration", 0);

  const presets = state?.capabilities.presets ?? [];
  const supervised = state?.ble?.supervisor.toys[toy.id];
  const rssi =
    state?.ble?.advertisements.find(
      (row) => row.address && toy.ble?.address && row.address === toy.ble.address,
    )?.rssi ?? null;

  // Slider ticks already wake /ws via runtime.bump(); force-refreshing /state after
  // every motor write races the BLE inventory path and adds tunnel RTT for no benefit.
  const settle = () => void refresh();
  const reload = () => void refresh(true);

  const [runPreset, presetPending] = useAsyncAction(
    (name: string) => api.command.preset({ toy_id: toy.id, name, time: duration }),
    { errorTitle: "Preset failed", onDone: settle },
  );
  const [stopToy, stopping] = useAsyncAction(() => api.command.stopToy(toy.id), {
    errorTitle: "Stop failed",
    onDone: settle,
  });
  const [reconnect, reconnecting] = useAsyncAction(() => api.ble.reconnect(toy.id), {
    success: `${toy.nick_name} reconnected`,
    errorTitle: "Reconnect failed",
    onDone: reload,
  });
  const [disconnect, disconnecting] = useAsyncAction(() => api.ble.disconnect(toy.id), {
    success: `${toy.nick_name} disconnected`,
    errorTitle: "Disconnect failed",
    onDone: reload,
  });
  const [forget, forgetting] = useAsyncAction(() => api.ble.forget(toy.id), {
    success: `${toy.nick_name} removed`,
    errorTitle: "Could not remove the device",
    onDone: reload,
  });

  const offline = !toy.online;
  const isBle = toy.ble !== null;
  const busy = reconnecting || disconnecting || forgetting;

  return (
    <Card
      className={cn(
        "flex h-full flex-col gap-3 transition-opacity",
        offline && "opacity-80",
      )}
    >
      <CardHeader className="gap-2">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <span className="truncate font-semibold">{toy.nick_name}</span>
              {offline ? (
                <Badge variant="secondary" className="gap-1">
                  <BluetoothOff /> Offline
                </Badge>
              ) : session ? (
                <Badge variant="default" className="animate-pulse-soft gap-1">
                  Playing
                </Badge>
              ) : null}
            </div>
            <div className="text-muted-foreground mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs">
              <span className="inline-flex items-center gap-1">
                {isBle ? <Bluetooth className="size-3.5" /> : <Cloud className="size-3.5" />}
                {isBle ? "Bluetooth" : "Lovense app"}
              </span>
              {toyTypeLabel(toy.toy_type) ? <span>{toyTypeLabel(toy.toy_type)}</span> : null}
              {toy.battery !== null ? (
                <span className={cn("inline-flex items-center gap-1", batteryTone(toy.battery))}>
                  {toy.battery <= 20 ? (
                    <BatteryLow className="size-3.5" />
                  ) : (
                    <Battery className="size-3.5" />
                  )}
                  {toy.battery}%
                </span>
              ) : null}
              <SignalMeter rssi={rssi} />
            </div>
          </div>

          <Button
            variant={session || features.some((f) => (levels.get(slotKey(toy.id, f)) ?? 0) > 0) ? "destructive" : "ghost"}
            size="icon"
            disabled={offline || stopping}
            onClick={() => void stopToy()}
            title="Stop this device"
          >
            {stopping ? <Loader2 className="animate-spin" /> : <Square />}
            <span className="sr-only">Stop {toy.nick_name}</span>
          </Button>
        </div>

        {offline ? (
          <div className="flex min-h-9 flex-wrap items-center gap-2">
            {isBle && canManageBle ? (
              <Button size="sm" disabled={busy} onClick={() => void reconnect()}>
                {reconnecting ? <Loader2 className="animate-spin" /> : <Plug />}
                Reconnect
              </Button>
            ) : null}
            <span className="text-muted-foreground text-xs">
              {supervised?.last_error
                ? supervised.last_error
                : supervised && supervised.retry_in_sec > 0
                  ? `Retrying in ${formatSeconds(supervised.retry_in_sec)}`
                  : "Waiting for the device"}
            </span>
          </div>
        ) : (
          // Reserve the offline-action row so online/offline cards share a header height.
          <div className="min-h-9" aria-hidden />
        )}
      </CardHeader>

      <CardContent className="flex flex-1 flex-col gap-4">
        <div className="space-y-3">
          {features.map((feature) => (
            <FeatureSlider
              key={feature}
              toyId={toy.id}
              feature={feature}
              range={featureRange(state, feature)}
              serverLevel={levels.get(slotKey(toy.id, feature)) ?? 0}
              disabled={offline}
            />
          ))}
        </div>

        <div className="mt-auto space-y-4">
          <Separator />

          <div className="space-y-2">
            <div className="flex items-center justify-between gap-2">
              <span className="text-muted-foreground text-xs font-medium tracking-wide uppercase">
                Modes
              </span>
              {session?.remaining_sec !== null && session?.remaining_sec !== undefined ? (
                <span className="text-muted-foreground font-mono text-xs tabular-nums">
                  {formatSeconds(session.remaining_sec)} left
                </span>
              ) : null}
            </div>

            <DurationPicker value={duration} onChange={setDuration} />

            <div className="flex flex-wrap gap-2">
              {presets.map((preset) => {
                const active = session?.kind === "preset" && session.preset === preset;
                return (
                  <Button
                    key={preset}
                    variant={active ? "default" : "outline"}
                    size="sm"
                    disabled={offline || presetPending}
                    onClick={() => (active ? void stopToy() : void runPreset(preset))}
                  >
                    {presetLabel(preset)}
                  </Button>
                );
              })}
              <PatternDialog toy={toy} duration={duration} disabled={offline} />
              <PulseDialog toy={toy} disabled={offline} />
            </div>
          </div>

          {isBle && canManageBle ? (
            <div className="flex flex-wrap items-center gap-2">
              {!offline ? (
                <Button
                  variant="ghost"
                  size="sm"
                  disabled={busy}
                  onClick={() => void disconnect()}
                  className="text-muted-foreground"
                >
                  {disconnecting ? <Loader2 className="animate-spin" /> : <BluetoothOff />}
                  Disconnect
                </Button>
              ) : null}
              <Button
                variant="ghost"
                size="sm"
                disabled={busy}
                onClick={() => void forget()}
                className="text-muted-foreground hover:text-destructive"
              >
                {forgetting ? <Loader2 className="animate-spin" /> : <Trash2 />}
                Forget
              </Button>
              {supervised && supervised.reconnects > 0 ? (
                <span className="text-muted-foreground ml-auto text-xs">
                  {supervised.reconnects} auto-reconnect{supervised.reconnects === 1 ? "" : "s"}
                </span>
              ) : null}
            </div>
          ) : null}
        </div>
      </CardContent>
    </Card>
  );
}
