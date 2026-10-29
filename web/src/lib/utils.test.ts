/// <reference types="node" />
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { cn } from "@/lib/utils";

// Vitest stubs CSS imports, ?raw included, so the stylesheet is read from disk.
const styles = readFileSync("src/styles.css", "utf8");
const tokens = (prefix: string) => [...styles.matchAll(new RegExp(`--${prefix}-([a-z]+):`, "g"))].map((m) => m[1]);

describe("cn", () => {
  it.each(tokens("text"))("keeps text-%s beside a text color", (size) => {
    expect(cn(`text-${size} text-silt`, "text-brass")).toBe(`text-${size} text-brass`);
  });

  it.each(tokens("shadow"))("lets a later shadow replace shadow-%s", (shadow) => {
    expect(cn(`shadow-${shadow}`, "shadow-none")).toBe("shadow-none");
  });
});
