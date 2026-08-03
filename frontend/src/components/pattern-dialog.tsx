import { Loader2, Play, Square, Waves } from "lucide-react";
import { useMemo, useState } from "react";

import { PatternEditor } from "@/components/pattern-editor";
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
import { controllableFeatures, modeSessionFor } from "@/lib/derive";
import { featureLabel, presetLabel } from "@/lib/format";
import type { ToyView } from "@/lib/types";

interface Props {
  toy: ToyView;
  duration: number;
  disabled?: boolean;
}

export function PatternDialog({ toy, duration, disabled }: Props) {
  const { state, refresh } = useService();
  const limits = state?.capabilities.pattern_limits;
  const maxLevel = limits?.max_level ?? 20;
  const maxSteps = limits?.max_steps ?? 50;
  const [intervalMin, intervalMax] = limits?.interval_ms ?? [100, 1000];
  const templates = state?.capabilities.pattern_templates ?? {};
  const features = useMemo(() => controllableFeatures(toy, state), [state, toy]);
  const session = modeSessionFor(state?.tasks ?? [], toy.id);
  const running = session?.kind === "pattern";

  const [open, setOpen] = useState(false);
  const [steps, setSteps] = useState<number[]>(() =>
    Object.values(templates)[0]?.slice(0, 12) ?? [4, 8, 12, 16, 12, 8],
  );
  const [interval, setInterval] = useState(200);
  const [motors, setMotors] = useState<string[]>([]);

  const [play, playing] = useAsyncAction(
    () =>
      api.command.pattern({
        toy_id: toy.id,
        pattern: steps,
        interval,
        actions: motors.length ? motors : null,
        time: duration,
      }),
    {
      errorTitle: "Pattern failed",
      onDone: () => void refresh(),
    },
  );
  const [stop, stopping] = useAsyncAction(() => api.command.stopToy(toy.id), {
    errorTitle: "Stop failed",
    onDone: () => void refresh(),
  });

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant={running ? "default" : "outline"} size="sm" disabled={disabled}>
          <Waves /> Pattern
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>Pattern · {toy.nick_name}</DialogTitle>
          <DialogDescription>
            The device replays these levels in a loop, one step per interval.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-2">
          <Label>Start from</Label>
          <div className="flex flex-wrap gap-2">
            {Object.entries(templates).map(([name, values]) => (
              <Button
                key={name}
                variant="secondary"
                size="sm"
                onClick={() => setSteps(values.slice(0, maxSteps))}
              >
                {presetLabel(name)}
              </Button>
            ))}
          </div>
        </div>

        <PatternEditor
          steps={steps}
          onChange={setSteps}
          maxLevel={maxLevel}
          maxSteps={maxSteps}
        />

        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <Label htmlFor="pattern-interval">Step length</Label>
            <span className="text-muted-foreground font-mono text-xs tabular-nums">
              {interval} ms
            </span>
          </div>
          <Slider
            id="pattern-interval"
            aria-label="Step length in milliseconds"
            value={[interval]}
            min={intervalMin}
            max={intervalMax}
            step={50}
            onValueChange={([next]) => setInterval(next ?? intervalMin)}
          />
        </div>

        {features.length > 1 ? (
          <div className="space-y-2">
            <Label>Motors</Label>
            <ToggleGroup
              type="multiple"
              value={motors}
              onValueChange={setMotors}
              className="w-full flex-wrap"
            >
              {features.map((feature) => (
                <ToggleGroupItem key={feature} value={feature}>
                  {featureLabel(feature)}
                </ToggleGroupItem>
              ))}
            </ToggleGroup>
            <p className="text-muted-foreground text-xs">
              Nothing selected means every motor follows the pattern.
            </p>
          </div>
        ) : null}

        <DialogFooter>
          {running ? (
            <Button variant="destructive" onClick={() => void stop()} disabled={stopping}>
              {stopping ? <Loader2 className="animate-spin" /> : <Square />} Stop
            </Button>
          ) : null}
          <Button
            onClick={async () => {
              const ok = await play();
              if (ok) setOpen(false);
            }}
            disabled={playing || steps.length === 0}
          >
            {playing ? <Loader2 className="animate-spin" /> : <Play />} Play
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
