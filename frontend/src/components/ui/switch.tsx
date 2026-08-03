import * as SwitchPrimitive from "@radix-ui/react-switch";
import type * as React from "react";

import { cn } from "@/lib/utils";

function Switch({ className, ...props }: React.ComponentProps<typeof SwitchPrimitive.Root>) {
  return (
    <SwitchPrimitive.Root
      data-slot="switch"
      className={cn(
        [
          "peer inline-flex h-7 w-12 shrink-0 items-center rounded-full border border-transparent",
          "data-[state=checked]:bg-primary data-[state=unchecked]:bg-input",
          "focus-visible:ring-ring/40 focus-visible:ring-[3px] focus-visible:outline-none",
          "disabled:cursor-not-allowed disabled:opacity-50",
          "transition-[background-color,border-color] duration-300 ease-[cubic-bezier(0.22,1,0.36,1)]",
        ].join(" "),
        className,
      )}
      {...props}
    >
      <SwitchPrimitive.Thumb
        data-slot="switch-thumb"
        className={[
          "bg-background pointer-events-none block size-6 rounded-full shadow-sm ring-0",
          "transition-transform duration-300 ease-[cubic-bezier(0.22,1,0.36,1)]",
          "data-[state=checked]:translate-x-[1.35rem] data-[state=unchecked]:translate-x-0.5",
        ].join(" ")}
      />
    </SwitchPrimitive.Root>
  );
}

export { Switch };
