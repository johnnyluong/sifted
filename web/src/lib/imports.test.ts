import { describe, expect, it } from "vitest";
import {
  activeImport,
  formatCountdown,
  formatDuration,
  formatGap,
  formatPerPost,
  formatUsd,
  progress,
} from "@/lib/imports";
import { importView } from "@/test/fixtures";

describe("formatting", () => {
  it("rounds durations to what a person plans around", () => {
    expect(formatDuration(18000)).toBe("5 hours");
    expect(formatDuration(9000)).toBe("2.5 hours");
    expect(formatDuration(271800)).toBe("3 days");
    expect(formatDuration(540)).toBe("9 min");
  });

  it("shows cents, and four places for a per-post figure", () => {
    expect(formatUsd(9.105)).toBe("$9.11");
    expect(formatUsd(0.0714)).toBe("$0.07");
    expect(formatPerPost(0.0238)).toBe("$0.0238");
  });

  it("says the pace the way the preview reads it", () => {
    expect(formatGap(180)).toBe("3 minutes");
    expect(formatGap(60)).toBe("minute");
    expect(formatGap(10)).toBe("10 seconds");
  });

  it("counts down to the next release", () => {
    const now = new Date("2026-10-23T14:00:00Z");
    expect(formatCountdown("2026-10-23T14:02:10Z", now)).toBe("2m 10s");
    expect(formatCountdown("2026-10-23T14:00:45Z", now)).toBe("45s");
    expect(formatCountdown("2026-10-23T13:59:00Z", now)).toBe("0s");
    expect(formatCountdown("2026-10-23T17:05:00Z", now)).toBe("3h 05m");
  });
});

describe("the Inbox banner's import", () => {
  it("follows the oldest import still running or paused", () => {
    const list = [
      importView({ id: 3, phase: "preview" }),
      importView({ id: 2, phase: "running" }),
      importView({ id: 1, phase: "paused" }),
    ];
    expect(activeImport(list)?.id).toBe(1);
    expect(activeImport([importView({ phase: "finished" })])).toBeUndefined();
  });

  it("measures progress over what was chosen", () => {
    const counts = { ...importView().counts, released: 142, waiting: 228 };
    expect(progress({ counts })).toEqual({ done: 142, total: 370 });
  });
});
