import type * as React from "react";

import { cn } from "@/lib/utils";

function Skeleton({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="skeleton"
      className={cn("bg-secondary/70 animate-pulse-soft rounded-lg", className)}
      {...props}
    />
  );
}

export { Skeleton };
