import { Loader2, Play, Timer } from "lucide-react";
import { useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { Slider } from "@/components/ui/slider";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { useAsyncAction } from "@/hooks/use-async-action";
import { useService } from "@/hooks/use-service";
import { api } from "@/lib/api";
import { controllableFeatures, featureRange } from "@/lib/derive";
import { featureLabel } from "@/lib/format";
import type { ToyView } from "@/lib/types";

const SECONDS = [1, 2, 3, 5, 10];

/**
 * Device-side pulsing (`loop_on_time` / `loop_off_time`).
 *
 * The toy itself alternates on and off, so the rhythm survives a dropped Wi-Fi link or
 * a phone that falls asleep — unlike a loop driven from the browser.
 */
export function PulseDialog({ toy, disabled }: { toy: ToyView; disabled?: boolean }) {
  const { state, refresh } = useService();
  const features = useMemo(() => controllableFeatures(toy, state), [state, toy]);
  const [open, setOpen] = useState(false);
  const [feature, setFeature] = useState(features[0] ?? "Vibrate");
  const [level, setLevel] = useState(() => Math.round(featureRange(state, features[0] ?? "Vibrate")[1] / 2));
  const [onTime, setOnTime] = useState(2);
  const [offTime, setOffTime] = useState(2);
  const [min, max] = featureRange(state, feature);

  const [start, starting] = useAsyncAction(
    () =>
      api.command.fn({
        toy_id: toy.id,
        actions: { [feature]: level },
        time: 0,
        loop_on_time: onTime,
        loop_off_time: offTime,
      }),
    { errorTitle: "Pulse failed", onDone: () => void refresh() },
  );

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="outline" size="sm" disabled={disabled}>
          <Timer /> Pulse
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Pulse · {toy.nick_name}</DialogTitle>
          <DialogDescription>
            The device keeps the rhythm on its own, so it survives a network hiccup.
          </DialogDescription>
        </DialogHeader>

        {features.length > 1 ? (
          <div className="space-y-2">
            <Label>Motor</Label>
            <ToggleGroup
              type="single"
              value={feature}
              onValueChange={(next) => next && setFeature(next)}
              className="w-full flex-wrap"
            >
              {features.map((item) => (
                <ToggleGroupItem key={item} value={item}>
                  {featureLabel(item)}
                </ToggleGroupItem>
              ))}
            </ToggleGroup>
          </div>
        ) : null}

        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <Label htmlFor="pulse-level">Strength</Label>
            <span className="text-muted-foreground font-mono text-xs tabular-nums">
              {level}/{max}
            </span>
          </div>
          <Slider
            id="pulse-level"
            aria-label="Strength"
            value={[level]}
            min={Math.max(min, 1)}
            max={max}
            step={1}
            onValueChange={([next]) => setLevel(next ?? 1)}
          />
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-2">
            <Label>On</Label>
            <ToggleGroup
              type="single"
              value={String(onTime)}
              onValueChange={(next) => next && setOnTime(Number(next))}
              className="w-full"
            >
              {SECONDS.map((value) => (
                <ToggleGroupItem key={value} value={String(value)} className="flex-1 px-2">
                  {value}s
                </ToggleGroupItem>
              ))}
            </ToggleGroup>
          </div>
          <div className="space-y-2">
            <Label>Off</Label>
            <ToggleGroup
              type="single"
              value={String(offTime)}
              onValueChange={(next) => next && setOffTime(Number(next))}
              className="w-full"
            >
              {SECONDS.map((value) => (
                <ToggleGroupItem key={value} value={String(value)} className="flex-1 px-2">
                  {value}s
                </ToggleGroupItem>
              ))}
            </ToggleGroup>
          </div>
        </div>

        <DialogFooter>
          <Button
            onClick={async () => {
              const ok = await start();
              if (ok) setOpen(false);
            }}
            disabled={starting}
          >
            {starting ? <Loader2 className="animate-spin" /> : <Play />} Start pulsing
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
