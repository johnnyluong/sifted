import type { ComponentProps, JSX } from "react";
import { cn } from "@/lib/utils";

export function Tag({ className, ...props }: ComponentProps<"span">): JSX.Element {
  return (
    <span
      className={cn("rounded-[5px] border border-mesh px-1.5 py-px font-mono text-micro text-silt", className)}
      {...props}
    />
  );
}
