import type { LucideIcon } from "lucide-react";
import { Archive, FileArchive, Layers, Newspaper, Smartphone, Target } from "lucide-react";
import type { NavCounts, Topic, TopicsView, UserAction } from "@/api";

export type Shelf = {
  id: keyof NavCounts;
  label: string;
  to: "/inbox" | "/kept" | "/archived";
  accepts?: UserAction;
};

const ARCHIVED = { id: "archived", label: "Archived", to: "/archived", accepts: "archive" } as const satisfies Shelf;

export const SHELVES: readonly Shelf[] = [
  { id: "inbox", label: "Inbox", to: "/inbox" },
  { id: "kept", label: "Kept", to: "/kept", accepts: "keep" },
  ARCHIVED,
];

export type Destination = {
  to: "/digests" | "/topics" | "/archived" | "/goals" | "/import" | "/share";
  label: string;
  hint: string;
  icon: LucideIcon;
  count?: keyof NavCounts;
};

export const DIGEST: Destination = {
  to: "/digests",
  label: "Digest",
  hint: "What to act on this week",
  icon: Newspaper,
};

export const TOPICS: Destination = {
  to: "/topics",
  label: "Topics",
  hint: "One brief per subject you keep saving",
  icon: Layers,
  count: "topics",
};

export const SETTINGS: readonly Destination[] = [
  { to: "/goals", label: "Goals", hint: "What every post is scored against", icon: Target },
  { to: "/import", label: "Import", hint: "Posts saved before Sift, from a Meta export", icon: FileArchive },
  { to: "/share", label: "Save from iPhone", hint: "Send posts from the share sheet", icon: Smartphone },
];

export const MORE: readonly Destination[] = [
  TOPICS,
  { to: ARCHIVED.to, label: ARCHIVED.label, hint: "Posts below your keep line", icon: Archive, count: ARCHIVED.id },
  ...SETTINGS,
];

export function inMore(pathname: string): boolean {
  return MORE.some((d) => pathname === d.to || pathname.startsWith(`${d.to}/`));
}

export function sidebarTopics(view: Pick<TopicsView, "groups">): Topic[] {
  return view.groups
    .flatMap((group) => group.topics)
    .filter((topic) => topic.kept > 0)
    .sort((a, b) => b.kept - a.kept || a.name.localeCompare(b.name));
}
