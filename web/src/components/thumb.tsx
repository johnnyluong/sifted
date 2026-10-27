import type { JSX, ReactNode } from "react";
import { cn } from "@/lib/utils";

const BOX = { 28: "size-7 rounded-[5px]", 40: "size-10 rounded-md", 72: "size-[72px] rounded-lg" } as const;

export type ThumbSize = keyof typeof BOX;

export function Thumb({
  url,
  size = 40,
  placeholder,
}: {
  url: string | null;
  size?: ThumbSize;
  placeholder: ReactNode;
}): JSX.Element {
  const box = BOX[size];
  if (url) {
    return <img src={url} alt="" loading="lazy" className={cn(box, "bg-pan object-cover")} />;
  }
  return (
    <span
      aria-hidden
      className={cn(box, "grid place-items-center border border-mesh bg-pan font-mono text-micro text-silt")}
    >
      {placeholder}
    </span>
  );
}
