import { Dices, Minus, Plus, RotateCcw } from "lucide-react";
import { useCallback, useRef } from "react";

import { Button } from "@/components/ui/button";
import { clamp, cn } from "@/lib/utils";

interface Props {
  steps: number[];
  onChange: (steps: number[]) => void;
  maxLevel: number;
  maxSteps: number;
  className?: string;
}

/**
 * Draw a pattern with a finger.
 *
 * Editing 20 numeric inputs on a phone is miserable, so the pattern is a strip of bars
 * you paint over: horizontal position picks the step, vertical position picks the
 * level. Pointer events (not touch events) are used so mouse, pen and touch share one
 * code path across Chrome, Firefox and Safari, and pointer capture keeps the drag alive
 * when the finger slides outside the strip.
 */
export function PatternEditor({ steps, onChange, maxLevel, maxSteps, className }: Props) {
  const stripRef = useRef<HTMLDivElement | null>(null);
  const paintingRef = useRef(false);

  const paint = useCallback(
    (clientX: number, clientY: number) => {
      const strip = stripRef.current;
      if (!strip || steps.length === 0) return;
      const rect = strip.getBoundingClientRect();
      const ratioX = clamp((clientX - rect.left) / rect.width, 0, 0.9999);
      const index = Math.floor(ratioX * steps.length);
      const ratioY = clamp(1 - (clientY - rect.top) / rect.height, 0, 1);
      const level = Math.round(ratioY * maxLevel);
      if (steps[index] === level) return;
      const next = [...steps];
      next[index] = level;
      onChange(next);
    },
    [maxLevel, onChange, steps],
  );

  const addStep = () => {
    if (steps.length >= maxSteps) return;
    onChange([...steps, steps[steps.length - 1] ?? Math.round(maxLevel / 2)]);
  };

  const removeStep = () => {
    if (steps.length <= 1) return;
    onChange(steps.slice(0, -1));
  };

  const randomize = () => {
    onChange(steps.map(() => Math.round(Math.random() * maxLevel)));
  };

  const ramp = () => {
    onChange(
      steps.map((_, index) =>
        Math.round(((index + 1) / steps.length) * maxLevel),
      ),
    );
  };

  return (
    <div className={cn("space-y-2", className)}>
      <div
        ref={stripRef}
        role="group"
        aria-label="Pattern steps"
        className="bg-secondary/50 flex h-32 touch-none items-end gap-[3px] rounded-xl p-2"
        onPointerDown={(event) => {
          paintingRef.current = true;
          event.currentTarget.setPointerCapture(event.pointerId);
          paint(event.clientX, event.clientY);
        }}
        onPointerMove={(event) => {
          if (!paintingRef.current) return;
          paint(event.clientX, event.clientY);
        }}
        onPointerUp={(event) => {
          paintingRef.current = false;
          event.currentTarget.releasePointerCapture(event.pointerId);
        }}
        onPointerCancel={() => {
          paintingRef.current = false;
        }}
      >
        {steps.map((level, index) => (
          <div
            key={index}
            className="flex h-full flex-1 items-end"
            title={`Step ${index + 1}: ${level}`}
          >
            <div
              className={cn(
                "w-full rounded-t-sm transition-[height]",
                level === 0 ? "bg-muted-foreground/30" : "bg-primary",
              )}
              style={{ height: `${Math.max(3, (level / maxLevel) * 100)}%` }}
            />
          </div>
        ))}
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <div className="flex items-center gap-1">
          <Button variant="outline" size="icon-sm" onClick={removeStep} disabled={steps.length <= 1}>
            <Minus />
            <span className="sr-only">Remove step</span>
          </Button>
          <span className="text-muted-foreground w-20 text-center text-xs tabular-nums">
            {steps.length} / {maxSteps}
          </span>
          <Button
            variant="outline"
            size="icon-sm"
            onClick={addStep}
            disabled={steps.length >= maxSteps}
          >
            <Plus />
            <span className="sr-only">Add step</span>
          </Button>
        </div>
        <Button variant="ghost" size="sm" onClick={ramp}>
          <RotateCcw /> Ramp
        </Button>
        <Button variant="ghost" size="sm" onClick={randomize}>
          <Dices /> Shuffle
        </Button>
      </div>
      <p className="text-muted-foreground text-xs">
        Drag across the bars to shape the pattern. Each step lasts one interval.
      </p>
    </div>
  );
}
