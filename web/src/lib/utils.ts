import { type ClassValue, clsx } from "clsx";
import { extendTailwindMerge } from "tailwind-merge";

// The size and shadow tokens from styles.css; unlisted, tailwind-merge takes text-micro for a color and drops it.
const twMerge = extendTailwindMerge({
  extend: { theme: { text: ["micro", "caption", "body", "reading", "heading", "page", "score"], shadow: ["float"] } },
});

export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}

export function httpLink(url: string | null | undefined): string | null {
  return url && /^https?:\/\//i.test(url) ? url : null;
}
