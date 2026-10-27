import { Link } from "@tanstack/react-router";
import type { JSX } from "react";
import type { Notice } from "@/api";
import { NOTICES } from "@/lib/vocabulary";

export function NoticeBanner({ notice }: { notice: Notice | null }): JSX.Element | null {
  if (notice === null) return null;
  const { title, body, link } = NOTICES[notice];
  return (
    <div
      role="status"
      className="mb-7 flex flex-wrap items-baseline gap-x-2.5 gap-y-1 surface px-4 py-3 text-[13px] text-silt"
    >
      <b className="font-semibold text-graphite">{title}</b>
      <span>{body}</span>
      {link && (
        <Link to={link.to} className="font-medium text-graphite underline underline-offset-2">
          {link.label}
        </Link>
      )}
    </div>
  );
}
