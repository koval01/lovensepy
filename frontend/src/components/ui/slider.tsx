import * as SliderPrimitive from "@radix-ui/react-slider";
import * as React from "react";

import { cn } from "@/lib/utils";

/**
 * Touch-first slider.
 *
 * `touch-action: none` on the root is what makes dragging work on iOS and Android:
 * without it the browser claims the gesture for scrolling and the thumb stutters or
 * never moves. The thumb is deliberately large (28px) so it stays usable with a thumb
 * on a phone, and the track has extra vertical padding to widen the hit area.
 */
function Slider({
  className,
  trackClassName,
  rangeClassName,
  "aria-label": ariaLabel,
  "aria-labelledby": ariaLabelledBy,
  ...props
}: React.ComponentProps<typeof SliderPrimitive.Root> & {
  trackClassName?: string;
  rangeClassName?: string;
}) {
  return (
    <SliderPrimitive.Root
      data-slot="slider"
      className={cn(
        "relative flex w-full touch-none items-center py-2 select-none data-[disabled]:opacity-50",
        className,
      )}
      {...props}
    >
      <SliderPrimitive.Track
        data-slot="slider-track"
        className={cn(
          "bg-secondary relative h-2.5 w-full grow overflow-hidden rounded-full",
          trackClassName,
        )}
      >
        <SliderPrimitive.Range
          data-slot="slider-range"
          className={cn("bg-primary absolute h-full", rangeClassName)}
        />
      </SliderPrimitive.Track>
      {/* The thumb carries role="slider", so the accessible name belongs here, not on the root. */}
      <SliderPrimitive.Thumb
        data-slot="slider-thumb"
        aria-label={ariaLabel}
        aria-labelledby={ariaLabelledBy}
        className={[
          "border-foreground/80 bg-background ring-ring/35 block size-7 shrink-0 rounded-full border-2 shadow-md",
          "transition-[box-shadow,transform,border-color] duration-300 ease-[cubic-bezier(0.22,1,0.36,1)]",
          "hover:scale-105 focus-visible:ring-4 focus-visible:outline-none active:scale-110",
        ].join(" ")}
      />
    </SliderPrimitive.Root>
  );
}

export { Slider };
