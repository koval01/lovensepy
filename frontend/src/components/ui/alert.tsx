import { cva, type VariantProps } from "class-variance-authority";
import type * as React from "react";

import { cn } from "@/lib/utils";

const alertVariants = cva(
  [
    "relative grid w-full grid-cols-[0_1fr] items-start gap-y-0.5 rounded-2xl border px-4 py-3 text-sm",
    "has-[>svg]:grid-cols-[calc(var(--spacing)*4)_1fr] has-[>svg]:gap-x-3",
    "[&>svg]:size-4 [&>svg]:translate-y-0.5",
    "transition-[border-color,background-color,opacity] duration-300 ease-[cubic-bezier(0.22,1,0.36,1)]",
  ].join(" "),
  {
    variants: {
      variant: {
        default: "bg-card text-card-foreground",
        info: "border-hairline bg-elevated text-foreground [&>svg]:text-foreground",
        warning: "border-border bg-secondary/80 text-foreground [&>svg]:text-muted-foreground",
        destructive:
          "border-destructive/25 bg-destructive/8 text-foreground [&>svg]:text-destructive",
      },
    },
    defaultVariants: { variant: "default" },
  },
);

function Alert({
  className,
  variant,
  ...props
}: React.ComponentProps<"div"> & VariantProps<typeof alertVariants>) {
  return (
    <div data-slot="alert" role="alert" className={cn(alertVariants({ variant }), className)} {...props} />
  );
}

function AlertTitle({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="alert-title"
      className={cn("col-start-2 font-medium tracking-tight", className)}
      {...props}
    />
  );
}

function AlertDescription({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="alert-description"
      className={cn("text-muted-foreground col-start-2 grid gap-1 text-sm", className)}
      {...props}
    />
  );
}

export { Alert, AlertDescription, AlertTitle };
