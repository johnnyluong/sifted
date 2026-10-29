import type { LucideIcon } from "lucide-react";
import { CookingPot, Lightbulb, ListOrdered, MapPin, Package, Shapes } from "lucide-react";
import type {
  BriefState,
  GoalCategory,
  Hold,
  ImportAction,
  ImportPhase,
  Item,
  ItemType,
  Notice,
  PauseReason,
  Source,
  Stage,
  TopicChooser,
  UserAction,
} from "@/api";

export const TYPES: Record<ItemType, { label: string; icon: LucideIcon }> = {
  place: { label: "Place", icon: MapPin },
  recipe: { label: "Recipe", icon: CookingPot },
  playbook: { label: "Playbook", icon: ListOrdered },
  idea: { label: "Idea", icon: Lightbulb },
  product: { label: "Product", icon: Package },
  other: { label: "Other", icon: Shapes },
};

export const SOURCES: Record<Source, { label: string; monogram: string }> = {
  instagram: { label: "Instagram", monogram: "IG" },
  threads: { label: "Threads", monogram: "TH" },
  image: { label: "Image", monogram: "IM" },
};

export const ACTIONS: Record<UserAction, { label: string; done: string }> = {
  keep: { label: "Keep anyway", done: "Kept" },
  archive: { label: "Archive", done: "Archived" },
  done: { label: "Mark done", done: "Marked done" },
  undone: { label: "Not done", done: "Marked not done" },
  retry: { label: "Retry", done: "Retrying" },
  reprocess: { label: "Reprocess", done: "Reprocessing" },
};

export const STAGE_LABELS: Record<Stage, string> = {
  fetch: "Download",
  media: "Transcribe",
  extract: "Extract",
  score: "Score",
};

export const CATEGORIES: Record<GoalCategory, string> = {
  personal: "Personal",
  professional: "Professional",
  entrepreneurial: "Entrepreneurial",
  other: "Other",
};

export const NOTICES: Record<Notice, { title: string; body: string; link?: { label: string; to: "/setup" } }> = {
  fake_llm: {
    title: "Fake LLM.",
    body: "Cards and scores come from keyword rules, not Claude. Set LLM_BACKEND=anthropic and an API key for real extraction.",
  },
  no_llm: {
    title: "No LLM configured.",
    body: "Links are downloaded and transcribed, then wait. Add ANTHROPIC_API_KEY to .env and restart; waiting items finish on their own.",
  },
  no_goals: {
    title: "No goals yet.",
    body: "Sift scores what you save against your goals.",
    link: { label: "Set up goals", to: "/setup" },
  },
};

const BOUGHT = { label: "Bought", done: "Marked bought" };
const NOT_BOUGHT = { label: "Not bought", done: "Back on your wishlist" };

export function actionWords(action: UserAction, item: Pick<Item, "wishlist_post">): { label: string; done: string } {
  if (item.wishlist_post && action === "done") return BOUGHT;
  if (item.wishlist_post && action === "undone") return NOT_BOUGHT;
  return ACTIONS[action];
}

export function primaryAction(item: Pick<Item, "actions" | "status">): UserAction | undefined {
  if (item.actions.includes("retry")) return "retry";
  if (item.actions.includes("keep")) return "keep";
  return item.status === "kept" ? "done" : undefined;
}

export const IMPORT_PHASES: Record<ImportPhase, string> = {
  preview: "Ready to import",
  running: "Importing",
  paused: "Paused",
  finished: "Imported",
  cancelled: "Cancelled",
};

export const IMPORT_ACTIONS: Record<ImportAction, { label: string; done: string }> = {
  start: { label: "Start import", done: "Import started" },
  pause: { label: "Pause", done: "Import paused" },
  resume: { label: "Resume", done: "Import resumed" },
  cancel: { label: "Cancel import", done: "Import cancelled" },
};

export const HOLDS: Record<Hold, (untilText: string | null) => string> = {
  in_flight: () => "Waiting for the current post to finish",
  daily_cap: (untilText) => (untilText ? `Daily limit reached. Resumes ${untilText}` : "Daily limit reached"),
  gap: (untilText) => (untilText ? `Next post in ${untilText}` : "Next post shortly"),
};

export const PAUSE_REASONS: Record<PauseReason, { text: string; alarm: boolean }> = {
  user: { text: "You paused this import. Nothing goes to Instagram until you resume it.", alarm: false },
  download_failures: {
    text: "The last 5 posts failed to download, so the import stopped to rest the secondary account. Run uv run sift doctor; if the account is fine, the posts were likely deleted, so Resume.",
    alarm: true,
  },
};

export const IMPORTED_LABEL = "Imported";

export const BRIEF_STATES: Record<BriefState, { label: string; note: string }> = {
  none: {
    label: "No brief yet",
    note: "Sift writes a brief once two or more kept posts share this topic and stop changing for half an hour.",
  },
  fresh: { label: "Up to date", note: "" },
  stale: { label: "Out of date", note: "New posts since this was written. It updates once they settle." },
  writing: { label: "Writing", note: "Writing the brief. This page updates when it lands." },
};

export const TOPIC_CHOOSERS: Record<TopicChooser, string> = {
  sift: "Sift's pick",
  you: "Your pick",
};
