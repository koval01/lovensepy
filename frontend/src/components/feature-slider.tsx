import { Loader2, Minus, Plus, Power } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Slider } from "@/components/ui/slider";
import { useLevelControl } from "@/hooks/use-level-control";
import { featureLabel } from "@/lib/format";
import { clamp, cn } from "@/lib/utils";

interface Props {
  toyId: string;
  feature: string;
  range: [number, number];
  serverLevel: number;
  disabled?: boolean;
  emphasis?: boolean;
  onSettled?: () => void;
}

export function FeatureSlider({
  toyId,
  feature,
  range,
  serverLevel,
  disabled,
  emphasis,
  onSettled,
}: Props) {
  const [min, max] = range;
  const { level, busy, change, commit } = useLevelControl({
    toyId,
    feature,
    serverLevel,
    onSettled,
  });

  const step = max <= 5 ? 1 : 1;
  const nudge = (delta: number) => commit(clamp(level + delta, min, max));

  return (
    <div className="space-y-1.5">
      <div className="flex items-baseline justify-between gap-2">
        <span
          className={cn(
            "flex items-center gap-1.5 text-sm font-medium",
            emphasis && "text-primary",
          )}
        >
          {featureLabel(feature)}
          {busy ? <Loader2 className="text-muted-foreground size-3 animate-spin" /> : null}
        </span>
        <span className="text-muted-foreground font-mono text-xs tabular-nums">
          {level}
          <span className="opacity-60">/{max}</span>
        </span>
      </div>

      <div className="flex items-center gap-2">
        <Button
          variant="ghost"
          size="icon-sm"
          disabled={disabled || level <= min}
          onClick={() => nudge(-1)}
          aria-label={`Decrease ${featureLabel(feature)}`}
        >
          <Minus />
        </Button>

        <Slider
          value={[level]}
          min={min}
          max={max}
          step={step}
          disabled={disabled}
          aria-label={featureLabel(feature)}
          onValueChange={([next]) => change(next ?? min)}
          onValueCommit={([next]) => commit(next ?? min)}
          className="flex-1"
          rangeClassName={emphasis ? "bg-primary" : undefined}
        />

        <Button
          variant="ghost"
          size="icon-sm"
          disabled={disabled || level >= max}
          onClick={() => nudge(1)}
          aria-label={`Increase ${featureLabel(feature)}`}
        >
          <Plus />
        </Button>

        <Button
          variant={level > 0 ? "secondary" : "ghost"}
          size="icon-sm"
          disabled={disabled || level === 0}
          onClick={() => commit(0)}
          aria-label={`Stop ${featureLabel(feature)}`}
          title="Stop this motor"
        >
          <Power />
        </Button>
      </div>
    </div>
  );
}
