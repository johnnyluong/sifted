import { notFound } from "@tanstack/react-router";
import { ITEM_TYPES, type ItemType } from "@/api";

export type LibrarySearch = { q?: string; goal?: number; type?: ItemType; topic?: number; label?: string };

export function parseLibrarySearch(raw: Record<string, unknown>): LibrarySearch {
  const type = ITEM_TYPES.find((t) => t === raw.type);
  return { q: text(raw.q), goal: positive(raw.goal), type, topic: positive(raw.topic), label: text(raw.label) };
}

export type TopicSearch = { label?: string };

export function parseTopicSearch(raw: Record<string, unknown>): TopicSearch {
  return { label: text(raw.label) };
}

function text(raw: unknown): string | undefined {
  return typeof raw === "string" && raw.trim() ? raw : undefined;
}

function positive(raw: unknown): number | undefined {
  return typeof raw === "number" && Number.isInteger(raw) && raw > 0 ? raw : undefined;
}

export function parseId(raw: string): number {
  if (!/^[1-9]\d{0,15}$/.test(raw)) throw notFound();
  return Number(raw);
}
