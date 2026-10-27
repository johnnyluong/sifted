import { cva, type VariantProps } from "class-variance-authority";
import { Slot } from "radix-ui";
import type { ComponentProps, JSX } from "react";
import { cn } from "@/lib/utils";

export const buttonVariants = cva(
  "inline-flex shrink-0 cursor-pointer items-center justify-center gap-1.5 whitespace-nowrap rounded-md border font-[560] transition-colors disabled:pointer-events-none disabled:opacity-50 [&_svg]:size-3.5 [&_svg]:shrink-0",
  {
    variants: {
      variant: {
        primary: "border-graphite bg-graphite text-sheet hover:opacity-90",
        secondary: "border-mesh bg-sheet text-graphite hover:bg-hover",
        ghost: "border-transparent text-silt hover:bg-pan-hover hover:text-graphite",
      },
      size: {
        sm: "relative h-[26px] px-3 text-[12.5px] max-[700px]:h-8 max-[700px]:hit-area-44",
        md: "h-[34px] px-3.5 text-[13px] max-[700px]:h-11 max-[700px]:px-4 max-[700px]:text-[15px]",
      },
    },
    defaultVariants: { variant: "secondary", size: "md" },
  },
);

type ButtonProps = ComponentProps<"button"> & VariantProps<typeof buttonVariants> & { asChild?: boolean };

export function Button({ className, variant, size, asChild = false, ...props }: ButtonProps): JSX.Element {
  const Comp = asChild ? Slot.Root : "button";
  return <Comp className={cn(buttonVariants({ variant, size }), className)} {...props} />;
}

export function chipClass(active = false): string {
  return cn(
    "relative inline-flex h-8 items-center gap-1.5 rounded-full border px-3 text-[13px] hit-area-44 max-[700px]:h-9",
    active ? "border-graphite bg-sheet font-[560] text-graphite" : "border-mesh text-ink-soft hover:bg-pan-hover",
  );
}
