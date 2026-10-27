import type { JSX } from "react";

export function SieveMark({ className }: { className?: string }): JSX.Element {
  return (
    <svg viewBox="0 0 32 32" className={className} aria-hidden fill="none" strokeLinecap="round" strokeWidth={3.5}>
      <path d="M5 8h22M9 16h14" className="stroke-graphite" />
      <path d="M13 24h6" className="stroke-brass" />
    </svg>
  );
}
