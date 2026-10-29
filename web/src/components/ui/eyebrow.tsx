import type { ComponentProps, JSX } from "react";
import { cn } from "@/lib/utils";

export function Eyebrow({
  as: As = "h2",
  className,
  ...props
}: ComponentProps<"h2"> & { as?: "h2" | "p" }): JSX.Element {
  return <As className={cn("font-mono text-micro text-silt uppercase tracking-[0.04em]", className)} {...props} />;
}
